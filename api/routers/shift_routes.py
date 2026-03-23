"""
Shift CRUD Route Handlers.

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
import logging
from typing import List
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.schemas.shift import ShiftCreate, ShiftRead
from app.db.session import get_db
from app.utils.date_normalization import normalize_to_canonical_week
from data.models import ShiftModel
from repositories.sql_repo import SQLShiftRepository
from api.deps import get_session_id
from api.routers.helpers import _map_model_to_shift_schema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["shifts"])


def _check_duplicate_shift_window(
    db: Session,
    session_id: str,
    name: str,
    start_time: str,
    end_time: str,
    exclude_shift_id: str | None = None,
) -> None:
    """Raises 409 if a shift with the same (session, name, start, end) exists.

    Args:
        db: Active SQLAlchemy session.
        session_id: Tenant identifier.
        name: Shift name to check.
        start_time: Raw start time (will be normalized to canonical week).
        end_time: Raw end time (will be normalized to canonical week).
        exclude_shift_id: Shift ID to exclude (for update operations).

    Raises:
        HTTPException: 409 Conflict when a duplicate is found.
    """
    canonical_start = normalize_to_canonical_week(start_time)
    canonical_end = normalize_to_canonical_week(end_time)

    query = db.query(ShiftModel).filter_by(
        session_id=session_id,
        name=name,
        start_time=canonical_start,
        end_time=canonical_end,
    )
    if exclude_shift_id:
        query = query.filter(ShiftModel.shift_id != exclude_shift_id)

    if query.first() is not None:
        raise HTTPException(
            409,
            detail="A shift with this exact name and time window already exists.",
        )


# ==========================================
# CRUD: SHIFTS (Fixed)
# ==========================================

@router.post("/shifts", response_model=ShiftRead, status_code=201)
async def create_shift(
    shift_in: ShiftCreate,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    try:
        _check_duplicate_shift_window(
            db, session_id, shift_in.name, shift_in.start_time, shift_in.end_time,
        )

        repo = SQLShiftRepository(db, session_id)
        domain_shift = repo.create_from_schema(shift_in)
        db.commit()

        # FIX: Include session_id in filter
        db_model = db.query(ShiftModel).filter_by(
            shift_id=domain_shift.shift_id,
            session_id=session_id
        ).first()

        if not db_model:
            raise HTTPException(500, detail="Shift was created but could not be retrieved")

        return _map_model_to_shift_schema(db_model)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to create shift: %s", e, exc_info=True)
        raise HTTPException(500, detail="Failed to create shift. Please try again or contact support.")

@router.get("/shifts", response_model=List[ShiftRead])
async def get_shifts(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0
):
    """Get shifts with optional pagination.

    Args:
        limit: Maximum number of shifts to return (default 100, max 500)
        offset: Number of shifts to skip for pagination
    """
    # Clamp limit to prevent excessive queries
    limit = min(max(1, limit), 500)
    offset = max(0, offset)

    # REPOSITORY READ: Ensures task hydration from JSON
    repo = SQLShiftRepository(db, session_id)
    domain_shifts = repo.get_all()

    # Apply pagination to results
    paginated_shifts = domain_shifts[offset:offset + limit]

    # Convert domain objects to API schema
    result = []
    for shift in paginated_shifts:
        # Serialize tasks back to JSON format
        tasks_json = repo._serialize_tasks_from_domain(shift.tasks) if shift.tasks else {}

        result.append({
            "shift_id": shift.shift_id,
            "name": shift.name,
            "start_time": shift.time_window.start.isoformat(),
            "end_time": shift.time_window.end.isoformat(),
            "tasks_data": tasks_json,  # Includes the full tasks array
            "session_id": session_id
        })
    return result

@router.put("/shifts/{shift_id}", response_model=ShiftRead)
async def update_shift(
    shift_id: str,
    shift_in: ShiftCreate,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Update a shift.

    Canonical date normalization is enforced by the ShiftCreate schema and
    SQLShiftRepository.create_from_schema().
    """
    try:
        # Verify target shift exists in this session before update.
        existing_model = db.query(ShiftModel).filter_by(
            shift_id=shift_id,
            session_id=session_id
        ).first()

        if not existing_model:
            raise HTTPException(404, detail=f"Shift '{shift_id}' not found")

        _check_duplicate_shift_window(
            db, session_id, shift_in.name, shift_in.start_time, shift_in.end_time,
            exclude_shift_id=shift_id,
        )

        # Perform update via canonicalized repository path.
        repo = SQLShiftRepository(db, session_id)
        shift_in.shift_id = shift_id
        repo.create_from_schema(shift_in)
        db.commit()

        # Read back from DB to confirm.
        db_model = db.query(ShiftModel).filter_by(
            shift_id=shift_id,
            session_id=session_id
        ).first()

        if not db_model:
            raise HTTPException(404, detail=f"Shift '{shift_id}' not found after update")

        return _map_model_to_shift_schema(db_model)
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to update shift: %s", e, exc_info=True)
        raise HTTPException(500, detail="Failed to update shift. Please try again or contact support.")

@router.delete("/shifts/{shift_id}", status_code=200)
async def delete_shift(
    shift_id: str,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Delete a shift by ID.

    Returns 404 if shift doesn't exist.
    """
    try:
        # Check existence first for proper REST compliance
        existing = db.query(ShiftModel).filter_by(
            shift_id=shift_id,
            session_id=session_id
        ).first()

        if not existing:
            raise HTTPException(404, detail=f"Shift '{shift_id}' not found")

        repo = SQLShiftRepository(db, session_id)
        repo.delete(shift_id)
        db.commit()
        return {"status": "deleted", "shift_id": shift_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to delete shift: %s", e, exc_info=True)
        raise HTTPException(500, detail="Failed to delete shift. Please try again or contact support.")

