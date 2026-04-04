"""FastAPI Application Entry Point.

This module initializes the FastAPI application with middleware for
session management and registers all API routes.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
import sqlalchemy
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from alembic import command
from alembic.config import Config as AlembicConfig

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.rate_limiter import limiter
from app.core.security_headers import SecurityHeadersMiddleware
from api.routes import router
from api.routes_constraints_schema import router as constraints_schema_router
from solver.constraints.definitions import register_core_constraints

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    """Configure root logger level from settings.

    Falls back to INFO if the provided level string is not a valid
    Python logging level name.

    Args:
        level: A log level name (e.g. "DEBUG", "INFO", "WARNING", "ERROR").
    """
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        force=True,
    )


def _attach_security_headers(response: Response) -> Response:
    """Apply the required security headers to a response object."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = (
            "max-age=63072000; includeSubDomains"
        )
    return response


def _build_internal_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Create a sanitized 500 response with security headers attached."""
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True,
    )
    if settings.is_production:
        response = JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. Please try again later."},
        )
    else:
        response = JSONResponse(
            status_code=500,
            content={"detail": f"[DEV] {type(exc).__name__}: {str(exc)[:500]}"},
        )
    return _attach_security_headers(response)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager that runs on startup and shutdown.
    GUARANTEES that database tables are created before the app accepts requests.

    IMPORTANT: Critical errors (DB unavailable) will crash the app intentionally.
    This is fail-fast behavior to prevent silent deployment failures.
    """
    _configure_logging(settings.log_level)

    logger.info("Running Alembic migrations...")
    # CRITICAL: Let DB errors propagate - app should NOT start if DB is unavailable
    alembic_cfg = AlembicConfig("alembic.ini")
    # Tell env.py to skip fileConfig() — we are running embedded inside uvicorn,
    # and fileConfig(disable_existing_loggers=True) would kill uvicorn's loggers,
    # silencing "Application startup complete" and all subsequent INFO messages.
    alembic_cfg.attributes["configure_logger"] = False
    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        from app.db.session import engine

        inspector = sqlalchemy.inspect(engine)
        existing_tables = inspector.get_table_names()
        if not existing_tables:
            raise RuntimeError("Alembic failed on an empty database") from exc
        raise
    logger.info("Database schema up to date")

    logger.info("Registering constraint definitions...")
    # CRITICAL: Constraint registration must succeed for solver to work
    register_core_constraints()
    logger.info("Constraint definitions registered successfully")

    logger.info("Running stale solver job recovery sweep...")
    from services.solver_service import reap_stale_jobs
    reap_stale_jobs()
    logger.info("Startup stale-job recovery sweep completed")

    yield  # Application runs here

    logger.info("Shutting down, cleaning up resources...")
    from services.solver_service import _shutdown_executor
    _shutdown_executor()

# Initialize FastAPI app with lifespan
app = FastAPI(
    title=settings.api_title,
    version=settings.api_version,
    description=settings.api_description,
    lifespan=lifespan
)

register_exception_handlers(app)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ========================================================================
# Middleware stack (FastAPI processes add_middleware in LIFO order:
# LAST added = OUTERMOST at runtime).
#
# Runtime order (outermost → innermost):
#   SecurityHeaders → ProxyHeaders → CORS → Session → SlowAPI → App
# ========================================================================
app.add_middleware(SlowAPIMiddleware)

# Add session middleware for signed cookies
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age,
    same_site="lax"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Configured via env or defaults
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cookie", "X-Requested-With"],
)


# SecurityHeaders MUST be outermost so it covers CORS preflights,
# error responses, and every other path through the middleware stack.
app.add_middleware(SecurityHeadersMiddleware)

@app.middleware("http")
async def session_id_middleware(request: Request, call_next):
    """
    Middleware to ensure session_id cookie is set.
    """
    session_id = request.cookies.get(settings.session_cookie_name)

    if not session_id:
        session_id = str(uuid.uuid4())
        request.state.session_id = session_id

    try:
        response = await call_next(request)
    except Exception as exc:
        response = _build_internal_error_response(request, exc)

    if hasattr(request.state, "session_id") and request.state.session_id:
        response.set_cookie(
            key=settings.session_cookie_name,
            value=request.state.session_id,
            max_age=settings.session_max_age,
            httponly=True,
            samesite="lax",
            secure=settings.cookie_secure  # HTTPS only in production
        )

    return response

# Global exception handler - hides internal errors from clients in production
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catches unhandled exceptions and returns a generic error message.
    Internal details are logged but not exposed to clients for security.
    """
    return _build_internal_error_response(request, exc)


# Register API routes
app.include_router(router)
app.include_router(constraints_schema_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "message": "Shift Scheduling API",
        "version": settings.api_version,
        "docs": "/docs"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint with database verification.

    Returns DB status for accurate health reporting to load balancers.
    """
    from sqlalchemy import text
    from app.db.session import SessionLocal

    db_status = "healthy"
    try:
        db = SessionLocal()
        try:
            # Simple query to verify DB connectivity
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Health check DB ping failed: {e}")
        db_status = "unhealthy"

    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "database": db_status
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
