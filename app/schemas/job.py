"""Job Schema Definitions.

Pydantic models for job submission and status responses.
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from enum import Enum
from datetime import datetime


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class JobSubmitRequest(BaseModel):
    """Request model for submitting a new solve job."""
    pass  # No parameters needed - uses session data


class Assignment(BaseModel):
    """Represents a single worker-shift assignment."""
    worker_name: str
    shift_name: str
    time: str
    task: str
    role_details: str
    score: float
    score_breakdown: str


class JobStatusResponse(BaseModel):
    """Response model for job status queries."""
    job_id: str
    status: JobStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    # Results (only populated when status is COMPLETED)
    result_status: Optional[str] = None  # "Optimal", "Feasible", "Infeasible"
    objective_value: Optional[float] = None
    assignments: Optional[List[Assignment]] = None
    violations: Optional[Dict[str, Any]] = None
    penalty_breakdown: Optional[Dict[str, Any]] = None
    theoretical_max_score: Optional[float] = None

    # Diagnostics (populated when result_status is "Infeasible")
    diagnosis_message: Optional[str] = None
