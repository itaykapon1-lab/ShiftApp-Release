"""Excel Import/Export Route Handlers.

Extracted from the monolithic api/routes.py.

THREAD-SAFETY NOTE:
    The three Excel routes offload synchronous pandas/openpyxl I/O to a
    background thread via ``asyncio.to_thread()``.  SQLAlchemy Sessions are
    NOT thread-safe, so each background thread creates its own ``Session``
    from ``SessionLocal`` and closes it in a ``finally`` block.  The
    ``Depends(get_db)`` session from the main thread is NOT passed into the
    background thread.
"""
import asyncio
import io
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limiter import limiter
from app.db.session import get_db, SessionLocal
from services.excel_service import ExcelService, ImportValidationException
from api.deps import get_session_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import-export"])


# ------------------------------------------------------------------
# Synchronous thread wrappers — each creates AND destroys its own
# SQLAlchemy session, guaranteeing thread-safe DB access.
# ------------------------------------------------------------------

def _run_import_in_thread(
    file_content: bytes, session_id: str
) -> Dict[str, Any]:
    """Execute the full import pipeline in a background thread.

    Creates a thread-local SQLAlchemy session, runs ExcelService.import_excel,
    and guarantees session closure via ``finally``.

    Args:
        file_content: Raw bytes of the uploaded Excel file.
        session_id: Tenant session identifier.

    Returns:
        Import result dict (worker/shift counts + optional warnings).

    Raises:
        ImportValidationException: If blocking validation errors are found.
        ValueError: If a parser or server error occurs during import.
    """
    db: Session = SessionLocal()
    try:
        service = ExcelService(db, session_id)
        return service.import_excel(file_content)
    finally:
        db.close()


def _run_export_in_thread(session_id: str) -> io.BytesIO:
    """Execute the export pipeline in a background thread.

    Args:
        session_id: Tenant session identifier.

    Returns:
        BytesIO buffer containing the generated Excel workbook.
    """
    db: Session = SessionLocal()
    try:
        service = ExcelService(db, session_id)
        return service.export_excel()
    finally:
        db.close()


def _run_state_export_in_thread(session_id: str) -> io.BytesIO:
    """Execute the full-state export pipeline in a background thread.

    Args:
        session_id: Tenant session identifier.

    Returns:
        BytesIO buffer containing the round-trip compatible Excel workbook.
    """
    db: Session = SessionLocal()
    try:
        service = ExcelService(db, session_id)
        return service.export_full_state()
    finally:
        db.close()


# --- EXCEL OPERATIONS ---

@router.post("/files/import")
@limiter.limit("10/minute")
async def import_excel(
    request: Request,
    session_id: str = Depends(get_session_id),
    file: UploadFile = File(...),
):
    """Import Excel file with streaming size validation.

    Reads file in chunks to prevent OOM from very large uploads.
    Rejects files early if they exceed the size limit.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel file.")

    try:
        # Streaming file size check - read in chunks and reject early if too large
        max_size = settings.max_file_size_bytes
        chunk_size = 1024 * 1024  # 1MB chunks
        content_chunks = []
        total_size = 0

        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            total_size += len(chunk)

            # Early rejection if size exceeds limit
            if total_size > max_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size is {settings.max_file_size_mb}MB.",
                )
            content_chunks.append(chunk)

        content = b''.join(content_chunks)

        # Offload synchronous pandas/openpyxl I/O to a worker thread.
        # The thread creates its own Session — see _run_import_in_thread.
        stats = await asyncio.to_thread(_run_import_in_thread, content, session_id)
        return {"status": "success", "imported": stats}
    except HTTPException:
        raise  # Re-raise HTTP exceptions (like 413)
    except ImportValidationException as e:
        # Structured validation errors - return detailed report
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Excel file contains validation errors",
                "validation_errors": e.validation_result.to_dict(),
                "summary": e.validation_result.format_summary()
            }
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Import failed unexpectedly: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="An error occurred during import. Please verify the file format and try again.")

@router.get("/files/export")
async def export_excel(
    session_id: str = Depends(get_session_id),
):
    buffer = await asyncio.to_thread(_run_export_in_thread, session_id)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=schedule_data.xlsx"}
    )


@router.get("/files/export-state")
async def export_full_state(
    session_id: str = Depends(get_session_id),
):
    """Export complete session state as round-trip compatible Excel.

    Creates an Excel file with Workers, Shifts, and Constraints sheets
    in the same format as the import expects, enabling:
    - Backup/restore workflows
    - Data migration between sessions
    - Round-trip editing (export -> modify -> re-import)

    Returns:
        StreamingResponse: Excel file with timestamped filename
    """
    from datetime import datetime

    buffer = await asyncio.to_thread(_run_state_export_in_thread, session_id)

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"shiftapp_state_{timestamp}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
