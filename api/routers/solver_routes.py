"""
Solver Route Handlers (trigger, status, diagnostics).

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
from typing import Dict
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.schemas.job import JobStatusResponse
from app.db.session import get_db
from services.solver_service import SolverService
from api.deps import get_session_id

router = APIRouter(tags=["solver"])

# --- SOLVER ---

@router.post("/solve", response_model=Dict[str, str])
async def solve(
    session_id: str = Depends(get_session_id)
):
    """
    Starts a solver job using ProcessPoolExecutor.

    The solver runs in a separate process to prevent blocking the API.
    Poll /status/{job_id} to track progress.

    Returns 409 Conflict if session already has an active job.
    """
    try:
        job_id = SolverService.start_job(session_id=session_id)
        return {"job_id": job_id}
    except ValueError as e:
        # Session already has an active job
        raise HTTPException(status_code=409, detail=str(e))

@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    session_id: str = Depends(get_session_id)
):
    """Get job status with session-scoped access control.

    Security: Jobs are filtered by session_id to prevent cross-user data leakage.
    """
    job_data = SolverService.get_job_status(job_id, session_id=session_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return job_data


@router.post("/solve/{job_id}/diagnose")
async def run_diagnostics(
    job_id: str,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """
    Trigger diagnostic analysis for a failed solver job.

    This endpoint is called on-demand when the user clicks "Run Diagnostics"
    in the frontend. It performs an incremental constraint analysis to
    identify which constraint(s) caused the infeasibility.

    Returns:
        dict: Contains the diagnosis message explaining the failure
    """
    # Check if job exists
    job_data = SolverService.get_job_status(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Check if job is in a failed/infeasible state
    result_status = job_data.get("result_status")
    if result_status not in ["Infeasible", None]:
        raise HTTPException(
            status_code=400,
            detail=f"Diagnostics only available for failed jobs. Current status: {result_status}"
        )

    # Run diagnostics
    diagnosis = SolverService.run_diagnostics(job_id, session_id)

    return {"diagnosis": diagnosis}
