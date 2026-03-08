"""
Excel Import/Export Route Handlers.

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from services.excel_service import ExcelService, ImportValidationException
from api.deps import get_session_id

router = APIRouter(tags=["import-export"])

# --- EXCEL OPERATIONS ---

@router.post("/files/import")
async def import_excel(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db),
    file: UploadFile = File(...)
):
    """Import Excel file with streaming size validation.

    Reads file in chunks to prevent OOM from very large uploads.
    Rejects files early if they exceed the size limit.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(400, "Invalid file format. Please upload an Excel file.")

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
                    413,
                    f"File too large. Maximum size is {settings.max_file_size_mb}MB."
                )
            content_chunks.append(chunk)

        content = b''.join(content_chunks)

        service = ExcelService(db, session_id)
        stats = service.import_excel(content)
        # ExcelService handles the commit internally in the corrected version
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
        raise HTTPException(400, detail=str(e))
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Internal server error: {str(e)}")

@router.get("/files/export")
async def export_excel(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    service = ExcelService(db, session_id)
    buffer = service.export_excel()
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=schedule_data.xlsx"}
    )


@router.get("/files/export-state")
async def export_full_state(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
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

    service = ExcelService(db, session_id)
    buffer = service.export_full_state()

    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"shiftapp_state_{timestamp}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
