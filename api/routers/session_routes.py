"""
Session Data Management Route Handlers.

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from data.models import WorkerModel, ShiftModel, SessionConfigModel
from api.deps import get_session_id

router = APIRouter(tags=["session"])

# ==========================================
# SESSION DATA MANAGEMENT
# ==========================================

@router.delete("/session/data")
async def reset_session_data(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Reset all data for the current session.

    Deletes all Workers, Shifts, and Constraints for the specified session.
    This operation is irreversible.

    Security: Only affects the current session (multi-tenant isolation).

    Returns:
        dict: Summary of deleted records
    """
    try:
        # Count before deletion for reporting
        worker_count = db.query(WorkerModel).filter_by(session_id=session_id).count()
        shift_count = db.query(ShiftModel).filter_by(session_id=session_id).count()

        # Check if constraints exist
        config = db.query(SessionConfigModel).filter_by(session_id=session_id).first()
        constraint_count = len(config.constraints) if config and config.constraints else 0

        # Delete in dependency order (constraints reference workers)
        if config:
            config.constraints = []
            db.commit()

        # Delete shifts
        db.query(ShiftModel).filter_by(session_id=session_id).delete()

        # Delete workers
        db.query(WorkerModel).filter_by(session_id=session_id).delete()

        # Commit all deletions
        db.commit()

        return {
            "status": "success",
            "deleted": {
                "workers": worker_count,
                "shifts": shift_count,
                "constraints": constraint_count
            },
            "message": f"Session data reset complete. Deleted {worker_count} workers, {shift_count} shifts, {constraint_count} constraints."
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Failed to reset session data: {str(e)}")
