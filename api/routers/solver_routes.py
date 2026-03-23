"""
Solver Route Handlers (trigger, status, diagnostics).

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
from typing import Dict
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.core.rate_limiter import limiter
from app.schemas.job import JobStatus, JobStatusResponse
from services.solver_service import SolverService
from services.diagnostic_service import DiagnosticService
from api.deps import get_session_id

router = APIRouter(tags=["solver"])

# --- SOLVER ---

@router.post("/solve", response_model=Dict[str, str])
@limiter.limit("3/minute")
async def solve(
    request: Request,
    session_id: str = Depends(get_session_id),
):
    """
    Starts a solver job using ProcessPoolExecutor.

    The solver runs in a separate process to prevent blocking the API.
    Poll /status/{job_id} to track progress.

    Returns 409 Conflict if session already has an active job.
    """
    job_id = SolverService.start_job(session_id=session_id)
    return {"job_id": job_id}

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
@limiter.limit("5/minute")
async def run_diagnostics(
    request: Request,
    job_id: str,
    session_id: str = Depends(get_session_id),
):
    """Trigger async diagnostic analysis for a failed solver job.

    Returns HTTP 202 Accepted. Poll GET /status/{job_id} for diagnosis_status
    and diagnosis_message when complete.
    """
    # Validate job exists and belongs to this session (multi-tenancy guard).
    job_data = SolverService.get_job_status(job_id, session_id=session_id)
    if not job_data:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Gate 1: Job must be in terminal FAILED state.
    # PENDING/RUNNING jobs have result_status=None which passed the old check.
    job_status = job_data.get("status")
    if job_status != JobStatus.FAILED:
        raise HTTPException(
            status_code=400,
            detail=f"Diagnostics only available for failed jobs. Current status: {job_status}",
        )

    # Gate 2: Failure must be mathematical (Infeasible), not an OS crash or timeout.
    # Running diagnostics on an OOM-crashed job will just cause another OOM crash
    # or return garbage — the diagnostic engine needs a solvable model to analyze.
    result_status = job_data.get("result_status")
    if result_status != "Infeasible":
        raise HTTPException(
            status_code=400,
            detail=f"Diagnostics only available for infeasible jobs. Result status: {result_status}",
        )

    try:
        DiagnosticService.start_diagnosis(job_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return JSONResponse(
        status_code=202,
        content={"job_id": job_id, "diagnosis_status": "PENDING"},
    )
