"""FastAPI exception handlers for domain exceptions.

Translates ShiftAppError subtypes into HTTP responses with safe messages.
Full error details are logged server-side but never exposed to clients.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    ImportValidationError,
    InternalError,
    ResourceConflictError,
    ResourceNotFoundError,
    ShiftAppError,
    SolverError,
    ValidationError,
)

logger = logging.getLogger(__name__)


async def _handle_not_found(request: Request, exc: ResourceNotFoundError) -> JSONResponse:
    """Maps ResourceNotFoundError to HTTP 404."""
    return JSONResponse(status_code=404, content={"detail": exc.safe_message})


async def _handle_conflict(request: Request, exc: ResourceConflictError) -> JSONResponse:
    """Maps ResourceConflictError to HTTP 409."""
    return JSONResponse(status_code=409, content={"detail": exc.safe_message})


async def _handle_validation(request: Request, exc: ValidationError) -> JSONResponse:
    """Maps ValidationError to HTTP 400."""
    return JSONResponse(status_code=400, content={"detail": exc.safe_message})


async def _handle_import_validation(request: Request, exc: ImportValidationError) -> JSONResponse:
    """Maps ImportValidationError to HTTP 400 with structured error report."""
    detail: dict | str
    if hasattr(exc.validation_result, "to_dict"):
        detail = {
            "message": "Excel file contains validation errors",
            "validation_errors": exc.validation_result.to_dict(),
            "summary": exc.validation_result.format_summary(),
        }
    else:
        detail = exc.safe_message
    return JSONResponse(status_code=400, content={"detail": detail})


async def _handle_solver_error(request: Request, exc: SolverError) -> JSONResponse:
    """Maps SolverError to HTTP 500, logging job context server-side."""
    logger.error(
        "SolverError on %s %s (job_id=%s): %s",
        request.method, request.url.path, exc.job_id, exc.internal_detail or exc.safe_message,
        exc_info=True,
    )
    return JSONResponse(status_code=500, content={"detail": exc.safe_message})


async def _handle_internal(request: Request, exc: InternalError) -> JSONResponse:
    """Maps InternalError to HTTP 500, logging internal detail server-side."""
    if exc.internal_detail:
        logger.error(
            "InternalError on %s %s: %s",
            request.method, request.url.path, exc.internal_detail,
            exc_info=True,
        )
    return JSONResponse(status_code=500, content={"detail": exc.safe_message})


async def _handle_base(request: Request, exc: ShiftAppError) -> JSONResponse:
    """Catch-all for ShiftAppError subclasses not handled above."""
    if exc.internal_detail:
        logger.error(
            "ShiftAppError on %s %s: %s",
            request.method, request.url.path, exc.internal_detail,
            exc_info=True,
        )
    return JSONResponse(status_code=500, content={"detail": exc.safe_message})


def register_exception_handlers(app: FastAPI) -> None:
    """Registers domain exception handlers on the FastAPI app.

    Must be called after app creation, before the app starts serving.
    """
    app.add_exception_handler(ResourceNotFoundError, _handle_not_found)
    app.add_exception_handler(ResourceConflictError, _handle_conflict)
    app.add_exception_handler(ValidationError, _handle_validation)
    app.add_exception_handler(ImportValidationError, _handle_import_validation)
    app.add_exception_handler(SolverError, _handle_solver_error)
    app.add_exception_handler(InternalError, _handle_internal)
    app.add_exception_handler(ShiftAppError, _handle_base)
