"""
Worker CRUD Route Handlers.

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.schemas.worker import WorkerCreate, WorkerRead
from app.db.session import get_db
from data.models import WorkerModel
from repositories.sql_repo import SQLWorkerRepository
from api.deps import get_session_id
from api.routers.helpers import _map_model_to_worker_schema

router = APIRouter(tags=["workers"])

# ==========================================
# CRUD: WORKERS (Fixed)
# ==========================================

@router.post("/workers", response_model=WorkerRead, status_code=201)
async def create_worker(
    worker_in: WorkerCreate,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    try:
        repo = SQLWorkerRepository(db, session_id)
        # 1. Logic & Validation via Repo
        domain_worker = repo.create_from_schema(worker_in)
        # 2. Commit Transaction
        db.commit()

        # 3. Read back directly from DB Model to ensure JSON structure is correct
        # FIX: Include session_id in filter to ensure we get the right record
        db_model = db.query(WorkerModel).filter_by(
            worker_id=domain_worker.worker_id,
            session_id=session_id
        ).first()

        if not db_model:
            raise HTTPException(500, detail="Worker was created but could not be retrieved")

        return _map_model_to_worker_schema(db_model)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Failed to create worker: {str(e)}")

@router.get("/workers", response_model=List[WorkerRead])
async def get_workers(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db),
    limit: Optional[int] = None,
    offset: int = 0
):
    """Get workers with optional pagination.

    Args:
        limit: Maximum number of workers to return (default: all workers, max 500 when provided)
        offset: Number of workers to skip for pagination
    """
    offset = max(0, offset)

    # Query DB models directly so _map_model_to_worker_schema can read the
    # raw JSON attributes (including availability) without a lossy domain round-trip.
    query = (
        db.query(WorkerModel)
        .filter(WorkerModel.session_id == session_id)
        .order_by(WorkerModel.worker_id)
    )
    total = query.count()
    if offset >= total and total > 0:
        return []

    if limit is None:
        db_models = query.offset(offset).all()
    else:
        safe_limit = min(max(1, limit), 500)
        db_models = query.offset(offset).limit(safe_limit).all()

    return [_map_model_to_worker_schema(m) for m in db_models]

@router.put("/workers/{worker_id}", response_model=WorkerRead)
async def update_worker(
    worker_id: str,
    worker_in: WorkerCreate,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    try:
        repo = SQLWorkerRepository(db, session_id)
        worker_in.worker_id = worker_id
        repo.create_from_schema(worker_in) # Upsert
        db.commit()

        # FIX: Include session_id in filter
        db_model = db.query(WorkerModel).filter_by(
            worker_id=worker_id,
            session_id=session_id
        ).first()

        if not db_model:
            raise HTTPException(404, detail=f"Worker '{worker_id}' not found after update")

        return _map_model_to_worker_schema(db_model)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Failed to update worker: {str(e)}")

@router.delete("/workers/{worker_id}", status_code=200)
async def delete_worker(
    worker_id: str,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Delete a worker by ID.

    Returns 404 if worker doesn't exist.
    """
    try:
        # Check existence first for proper REST compliance
        existing = db.query(WorkerModel).filter_by(
            worker_id=worker_id,
            session_id=session_id
        ).first()

        if not existing:
            raise HTTPException(404, detail=f"Worker '{worker_id}' not found")

        repo = SQLWorkerRepository(db, session_id)
        repo.delete(worker_id)
        db.commit()
        return {"status": "deleted", "worker_id": worker_id}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, detail=f"Failed to delete worker: {str(e)}")
