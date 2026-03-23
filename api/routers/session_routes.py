"""Session Data Management Route Handlers.

Provides the DELETE /session/data endpoint that resets all data for the
current session by deleting the parent SessionConfigModel row and relying
on database-level CASCADE to remove dependent workers, shifts, and solver jobs.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from data.models import WorkerModel, ShiftModel, SessionConfigModel
from api.deps import get_session_id

logger = logging.getLogger(__name__)

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

    Deletes only the parent SessionConfigModel row; database-level CASCADE
    automatically removes all dependent workers, shifts, and solver jobs.
    Future writes will recreate the session config lazily via the session guard.

    Security: Only affects the current session (multi-tenant isolation).

    Returns:
        dict: Summary of deleted records.
    """
    try:
        # Count before deletion for reporting
        worker_count = db.query(WorkerModel).filter_by(session_id=session_id).count()
        shift_count = db.query(ShiftModel).filter_by(session_id=session_id).count()

        config = db.query(SessionConfigModel).filter_by(session_id=session_id).first()
        constraint_count = len(config.constraints) if config and config.constraints else 0

        # Delete the parent row — CASCADE removes workers, shifts, solver_jobs.
        if config:
            db.delete(config)
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

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to reset session data: %s", e, exc_info=True)
        raise HTTPException(500, detail="Failed to reset session data. Please try again or contact support.")
