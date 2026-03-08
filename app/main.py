"""FastAPI Application Entry Point.

This module initializes the FastAPI application with middleware for
session management and registers all API routes.
"""

import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import settings
from app.db.session import engine, Base  # Import engine directly
from api.routes import router
from api.routes_constraints_schema import router as constraints_schema_router
from solver.constraints.definitions import register_core_constraints

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager that runs on startup and shutdown.
    GUARANTEES that database tables are created before the app accepts requests.

    IMPORTANT: Critical errors (DB unavailable) will crash the app intentionally.
    This is fail-fast behavior to prevent silent deployment failures.
    """
    logger.info("Initializing database schema...")
    # CRITICAL: Let DB errors propagate - app should NOT start if DB is unavailable
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified/created successfully")

    logger.info("Registering constraint definitions...")
    # CRITICAL: Constraint registration must succeed for solver to work
    register_core_constraints()
    logger.info("Constraint definitions registered successfully")

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,  # Configured via env or defaults
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add session middleware for signed cookies
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    max_age=settings.session_max_age,
    same_site="lax"
)

@app.middleware("http")
async def session_id_middleware(request: Request, call_next):
    """
    Middleware to ensure session_id cookie is set.
    """
    session_id = request.cookies.get(settings.session_cookie_name)

    if not session_id:
        session_id = str(uuid.uuid4())
        request.state.session_id = session_id

    response = await call_next(request)

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
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {exc}",
        exc_info=True
    )

    # In production, hide internal error details
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. Please try again later."}
        )

    # In development, show the actual error for debugging
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)}
    )


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