"""Database-backed job store for solver jobs.

Extracted from solver_service.py to give SolverJobStore a dedicated module
with a single responsibility: persisting solver job state to the database.
"""

import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.schemas.job import JobStatus
from data.models import SolverJobModel

logger = logging.getLogger(__name__)

# Only these solver result strings indicate a successful (COMPLETED) outcome.
# Any other value — including None, "Unknown", "Timeout" — maps to FAILED.
_SUCCESSFUL_STATUSES: frozenset[str] = frozenset({"Optimal", "Feasible"})


def _serialize_for_json(value: Any) -> Any:
    """Recursively converts values to JSON-safe payloads.

    Args:
        value: Any Python value to serialize.

    Returns:
        A JSON-serializable representation of the value.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Enum):
        return value.value

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if is_dataclass(value):
        return _serialize_for_json(asdict(value))

    if isinstance(value, dict):
        return {str(key): _serialize_for_json(item) for key, item in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_serialize_for_json(item) for item in value]

    # Last-resort fallback to avoid crashing persistence.
    return str(value)


class SolverJobStore:
    """Database-backed job store for solver jobs.

    Replaces the in-memory _job_store dictionary to support:
    - Multi-worker deployments
    - Server restarts
    - Process isolation (ProcessPoolExecutor)
    """

    @staticmethod
    def create_job(db: Session, session_id: str) -> str:
        """Creates a new job record in PENDING state.

        Args:
            db: Active SQLAlchemy session.
            session_id: The session identifier for multi-tenant isolation.

        Returns:
            The newly created job's UUID string.
        """
        job_id = str(uuid.uuid4())

        job = SolverJobModel(
            job_id=job_id,
            session_id=session_id,
            status=JobStatus.PENDING.value,
            created_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()

        logger.info(f"Created job {job_id} for session {session_id}")
        return job_id

    @staticmethod
    def get_job(db: Session, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves job status as a dictionary.

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier to look up.

        Returns:
            A dict of job fields, or None if the job does not exist.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if not job:
            return None

        return {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "status": JobStatus(job.status) if job.status else JobStatus.PENDING,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "error_message": job.error_message,
            "result_status": job.result_status,
            "objective_value": job.objective_value,
            "theoretical_max_score": job.theoretical_max_score,
            "assignments": job.assignments or [],
            "violations": job.violations or {},
            "penalty_breakdown": job.penalty_breakdown or {},
            "diagnosis_message": job.diagnosis_message,
        }

    @staticmethod
    def update_job_running(db: Session, job_id: str) -> None:
        """Marks job as RUNNING. Caller owns the DB session lifecycle.

        Args:
            db: Active SQLAlchemy session provided by the caller.
            job_id: The job identifier to update.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if job:
            job.status = JobStatus.RUNNING.value
            job.started_at = datetime.utcnow()
            logger.info(f"Job {job_id} marked as RUNNING")

    @staticmethod
    def update_job_completed(
        db: Session,
        job_id: str,
        result_status: str,
        objective_value: float,
        assignments: list,
        violations: dict,
        theoretical_max_score: Optional[float] = None,
        diagnosis_message: Optional[str] = None,
        penalty_breakdown: Optional[dict] = None,
    ) -> None:
        """Marks job as COMPLETED or FAILED with results. Caller owns the DB session.

        Args:
            db: Active SQLAlchemy session provided by the caller.
            job_id: The job identifier to update.
            result_status: The solver's result status string (e.g. 'Optimal', 'Feasible',
                'Infeasible').
            objective_value: The solver's objective score.
            assignments: List of assignment dictionaries.
            violations: Dict mapping constraint names to violation lists.
            theoretical_max_score: Optional maximum possible score for this schedule.
            diagnosis_message: Optional human-readable diagnosis text.
            penalty_breakdown: Optional dict of penalty breakdowns per constraint.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if job:
            safe_assignments = _serialize_for_json(assignments or [])
            safe_violations = _serialize_for_json(violations or {})
            safe_penalty_breakdown = _serialize_for_json(penalty_breakdown or {})

            violation_constraints_count = (
                len(safe_violations)
                if isinstance(safe_violations, dict)
                else 0
            )
            violation_entries_count = 0
            if isinstance(safe_violations, dict):
                for violation_items in safe_violations.values():
                    if isinstance(violation_items, list):
                        violation_entries_count += len(violation_items)

            logger.info(
                "Persisting solver job %s payload: assignments=%d, violation_constraints=%d, violation_entries=%d",
                job_id,
                len(safe_assignments) if isinstance(safe_assignments, list) else 0,
                violation_constraints_count,
                violation_entries_count,
            )

            job.status = (
                JobStatus.COMPLETED.value
                if result_status in _SUCCESSFUL_STATUSES
                else JobStatus.FAILED.value
            )
            job.completed_at = datetime.utcnow()
            job.result_status = result_status
            job.objective_value = objective_value
            job.assignments = safe_assignments
            job.violations = safe_violations
            job.penalty_breakdown = safe_penalty_breakdown
            job.theoretical_max_score = theoretical_max_score
            job.diagnosis_message = diagnosis_message
            logger.info(
                "Job %s marked as COMPLETED or FAILED with %d assignments",
                job_id,
                len(safe_assignments) if isinstance(safe_assignments, list) else 0,
            )

    @staticmethod
    def update_job_failed(db: Session, job_id: str, error_message: str) -> None:
        """Marks job as FAILED with error. Caller owns the DB session lifecycle.

        Args:
            db: Active SQLAlchemy session provided by the caller.
            job_id: The job identifier to update.
            error_message: Human-readable description of the failure.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if job:
            job.status = JobStatus.FAILED.value
            job.completed_at = datetime.utcnow()
            job.error_message = error_message
            logger.info(f"Job {job_id} marked as FAILED: {error_message}")

    @staticmethod
    def get_latest_completed_job(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
        """Gets the most recent completed job for a session (for Excel export).

        Args:
            db: Active SQLAlchemy session.
            session_id: The session identifier to filter by.

        Returns:
            A dict of job fields for the most recently completed job, or None.
        """
        job = (
            db.query(SolverJobModel)
            .filter_by(session_id=session_id)
            .filter(SolverJobModel.status.in_([JobStatus.COMPLETED.value, JobStatus.FAILED.value]))
            .order_by(SolverJobModel.completed_at.desc())
            .first()
        )
        if not job:
            return None

        return SolverJobStore.get_job(db, job.job_id)
