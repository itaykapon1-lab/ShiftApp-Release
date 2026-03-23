"""Database-backed job store for solver jobs.

Extracted from solver_service.py to give SolverJobStore a dedicated module
with a single responsibility: persisting solver job state to the database.
"""

import logging
import uuid
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.core.constants import SOLVER_STALE_JOB_BUFFER_SECONDS, SOLVER_TIMEOUT_MS
from app.schemas.job import JobStatus
from data.models import SolverJobModel
from repositories._session_guard import ensure_session_config_exists

logger = logging.getLogger(__name__)

# Only these solver result strings indicate a successful (COMPLETED) outcome.
# "Optimal" = CP-SAT proved this is the best possible schedule.
# "Feasible" = CP-SAT found a valid schedule but couldn't prove optimality
#              within the time limit.
# Any other value — including None, "Infeasible", "Unknown", "Timeout" — maps to FAILED.
_SUCCESSFUL_STATUSES: frozenset[str] = frozenset({"Optimal", "Feasible"})


def _serialize_for_json(value: Any) -> Any:
    """Recursively converts values to JSON-safe payloads.

    Args:
        value: Any Python value to serialize.

    Returns:
        A JSON-serializable representation of the value.
    """
    # Primitives are already JSON-safe — return as-is.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # Enums (e.g., JobStatus.COMPLETED) → their string value.
    if isinstance(value, Enum):
        return value.value

    # datetime/date objects → ISO-8601 strings (e.g., "2024-01-01T08:00:00").
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    # Dataclasses (e.g., TimeWindow, Requirement) → dict via asdict, then
    # recurse to handle any nested non-JSON-safe types.
    if is_dataclass(value):
        return _serialize_for_json(asdict(value))

    # Dicts: stringify keys (JSON requires string keys) and recurse on values.
    if isinstance(value, dict):
        return {str(key): _serialize_for_json(item) for key, item in value.items()}

    # Lists, tuples, sets → JSON arrays with each element recursively serialised.
    if isinstance(value, (list, tuple, set)):
        return [_serialize_for_json(item) for item in value]

    # Last-resort fallback: convert to string to avoid crashing persistence.
    # This handles unexpected types (e.g., custom domain objects) gracefully.
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
        # Generate a unique job ID (UUID4) that the frontend will poll for status.
        job_id = str(uuid.uuid4())

        # Ensure the parent session_config row exists (FK requirement).
        ensure_session_config_exists(db, session_id)

        # Insert a new row in the solver_jobs table in PENDING state.
        # The job transitions to RUNNING once the subprocess picks it up,
        # then to COMPLETED or FAILED when the solver finishes.
        job = SolverJobModel(
            job_id=job_id,
            session_id=session_id,
            status=JobStatus.PENDING.value,
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        # Flush (not commit) so the row is visible to subsequent queries
        # within this transaction.  The caller owns the commit — start_job()
        # will commit only after the post-insert race check passes.
        db.flush()

        logger.info("Created job %s for session %s", job_id, session_id)
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
        # Query explicit columns instead of materializing a full ORM entity.
        # This avoids flaky row-processing issues under threaded SQLite test
        # runs where status polling can overlap with background job updates.
        row = db.execute(
            select(
                SolverJobModel.job_id,
                SolverJobModel.session_id,
                SolverJobModel.status,
                SolverJobModel.created_at,
                SolverJobModel.started_at,
                SolverJobModel.completed_at,
                SolverJobModel.error_message,
                SolverJobModel.result_status,
                SolverJobModel.objective_value,
                SolverJobModel.theoretical_max_score,
                SolverJobModel.assignments,
                SolverJobModel.violations,
                SolverJobModel.penalty_breakdown,
                SolverJobModel.diagnosis_message,
                SolverJobModel.diagnosis_status,
                SolverJobModel.diagnosis_attempt,
                SolverJobModel.diagnosis_updated_at,
            ).where(SolverJobModel.job_id == job_id)
        ).mappings().first()
        if not row:
            return None

        # Convert the ORM model to a plain dict for the API layer.
        # JSON columns (assignments, violations, penalty_breakdown) may be None
        # if the job hasn't completed yet — default to empty collection types.
        return {
            "job_id": row["job_id"],
            "session_id": row["session_id"],
            "status": JobStatus(row["status"]) if row["status"] else JobStatus.PENDING,
            "created_at": row["created_at"],
            "started_at": row["started_at"],           # Set when PENDING → RUNNING
            "completed_at": row["completed_at"],       # Set when RUNNING → COMPLETED/FAILED
            "error_message": row["error_message"],     # Only populated on FAILED
            "result_status": row["result_status"],     # Solver outcome: "Optimal", "Infeasible", etc.
            "objective_value": row["objective_value"],  # Total schedule score (soft constraint sum)
            "theoretical_max_score": row["theoretical_max_score"],
            "assignments": row["assignments"] or [],           # List of {worker_id, shift_id, ...}
            "violations": row["violations"] or {},             # {constraint_name: [violation_details]}
            "penalty_breakdown": row["penalty_breakdown"] or {},  # Per-constraint penalty totals
            "diagnosis_message": row["diagnosis_message"],     # Human-readable infeasibility explanation
            "diagnosis_status": row["diagnosis_status"],         # Async diagnosis lifecycle state
            "diagnosis_attempt": row["diagnosis_attempt"],       # Fencing token for async retries
            "diagnosis_updated_at": row["diagnosis_updated_at"], # Timestamp of latest diagnosis transition
        }

    @staticmethod
    def update_job_running(db: Session, job_id: str) -> None:
        """Marks job as RUNNING. Caller owns the DB session lifecycle.

        Args:
            db: Active SQLAlchemy session provided by the caller.
            job_id: The job identifier to update.

        Raises:
            ValueError: If the job does not exist or is no longer in PENDING
                state (e.g., already reaped or cancelled while queued).
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if not job:
            raise ValueError(
                f"Job {job_id} not found — may have been reaped or deleted"
            )
        if job.status != JobStatus.PENDING.value:
            raise ValueError(
                f"Job {job_id} is no longer PENDING (current status: {job.status})"
            )
        # State transition: PENDING → RUNNING.
        # The caller (run_solver_in_process) owns the session and will
        # commit this change as part of its Unit of Work.
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.now(timezone.utc)
        logger.info("Job %s marked as RUNNING", job_id)

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
            # Recursively serialise all solver outputs to JSON-safe types.
            # The solver returns domain objects (TimeWindow, Enum, dataclass)
            # that SQLAlchemy's JSON column cannot store directly.
            safe_assignments = _serialize_for_json(assignments or [])
            safe_violations = _serialize_for_json(violations or {})
            safe_penalty_breakdown = _serialize_for_json(penalty_breakdown or {})

            # Count violations for the log message (operational telemetry).
            # violation_constraints_count = how many constraint types were violated.
            # violation_entries_count = total individual violation instances.
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

            # Determine terminal state: "Optimal" or "Feasible" → COMPLETED,
            # anything else ("Infeasible", "Timeout", None) → FAILED.
            job.status = (
                JobStatus.COMPLETED.value
                if result_status in _SUCCESSFUL_STATUSES
                else JobStatus.FAILED.value
            )
            job.completed_at = datetime.now(timezone.utc)
            job.result_status = result_status       # Raw solver status string
            job.objective_value = objective_value   # Total soft-constraint score
            job.assignments = safe_assignments      # JSON list of assignment dicts
            job.violations = safe_violations        # JSON dict of violations by constraint
            job.penalty_breakdown = safe_penalty_breakdown  # Per-constraint penalty sums
            job.theoretical_max_score = theoretical_max_score
            job.diagnosis_message = diagnosis_message
            logger.info(
                "Job %s marked as COMPLETED or FAILED with %d assignments",
                job_id,
                len(safe_assignments) if isinstance(safe_assignments, list) else 0,
            )
        else:
            logger.warning("update_job_completed: job %s not found (may have been reaped or deleted)", job_id)

    @staticmethod
    def update_job_failed(db: Session, job_id: str, error_message: str) -> None:
        """Marks job as FAILED with error. Caller owns the DB session lifecycle.

        If the job is already in a terminal state (COMPLETED or FAILED), this
        method logs a warning and returns without overwriting the existing status.

        Args:
            db: Active SQLAlchemy session provided by the caller.
            job_id: The job identifier to update.
            error_message: Human-readable description of the failure.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if job:
            # Guard: do not overwrite a terminal state.  A job that already
            # reached COMPLETED or FAILED must not be retroactively changed.
            if job.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value):
                logger.warning(
                    "update_job_failed: job %s is already in terminal state %s; "
                    "refusing to overwrite",
                    job_id, job.status,
                )
                return
            # State transition: PENDING/RUNNING → FAILED.  The error_message is
            # stored verbatim so the frontend can display a meaningful failure reason.
            job.status = JobStatus.FAILED.value
            job.completed_at = datetime.now(timezone.utc)
            job.error_message = error_message
            logger.info("Job %s marked as FAILED: %s", job_id, error_message)
        else:
            logger.warning("update_job_failed: job %s not found (may have been reaped or deleted)", job_id)

    @staticmethod
    def get_active_job_id(db: Session, session_id: str) -> str | None:
        """Returns the job_id of any active (PENDING/RUNNING) job for this session.

        Args:
            db: Active SQLAlchemy session.
            session_id: The session identifier.

        Returns:
            The active job's ID, or None if no active job exists.
        """
        active_job = (
            db.query(SolverJobModel)
            .filter_by(session_id=session_id)
            .filter(SolverJobModel.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
            .first()
        )
        return active_job.job_id if active_job else None

    @staticmethod
    def count_active_jobs(db: Session, session_id: str) -> int:
        """Counts PENDING or RUNNING jobs for a session.

        Used for post-insert race detection in optimistic concurrency control.

        Args:
            db: Active SQLAlchemy session.
            session_id: The session identifier.

        Returns:
            The number of active (non-terminal) jobs for this session.
        """
        return (
            db.query(SolverJobModel)
            .filter_by(session_id=session_id)
            .filter(SolverJobModel.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
            .count()
        )

    @staticmethod
    def update_diagnosis_message(db: Session, job_id: str, message: str) -> None:
        """Persists a diagnosis message on an existing job record.

        Unlike other ``update_*`` methods, this method commits the transaction
        internally.  The caller does NOT need to call ``db.commit()`` after
        invoking this method.

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier to update.
            message: The human-readable diagnosis text.
        """
        job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
        if job:
            job.diagnosis_message = message
            db.commit()
        else:
            logger.warning("update_diagnosis_message: job %s not found", job_id)

    # Maximum seconds a job may remain PENDING before being reaped.
    # UX decision: 30 seconds is the absolute maximum queue wait time.
    PENDING_TIMEOUT_SECONDS: int = 30

    @staticmethod
    def reap_stale_jobs(
        db: Session,
        now: Optional[datetime] = None,
        timeout_ms: int = SOLVER_TIMEOUT_MS,
        grace_seconds: int = SOLVER_STALE_JOB_BUFFER_SECONDS,
    ) -> int:
        """Transitions stale RUNNING and orphaned PENDING jobs to FAILED.

        Also sweeps zombie diagnostic statuses (PENDING/RUNNING) that were
        abandoned after a hard process crash (SIGKILL) where the done callback
        never fired.

        RUNNING jobs are considered stale when ``started_at`` exceeds the
        ``timeout_ms + grace_seconds`` window.

        PENDING jobs use a strict 30-second threshold: if the executor has
        not picked them up within that window, the server is under too much
        load and the user should retry.

        Diagnostic zombies use ``diagnosis_updated_at`` as the anchor so fresh
        retries are not reaped based on the original solve completion time.

        Returns:
            The total number of reaped items (solver jobs + diagnostic zombies).
        """
        current_time = now or datetime.now(timezone.utc)
        running_cutoff = current_time - timedelta(
            milliseconds=timeout_ms, seconds=grace_seconds,
        )

        # Sweep 1: stale RUNNING jobs (stuck solver processes).
        stale_running = (
            db.query(SolverJobModel)
            .filter(SolverJobModel.status == JobStatus.RUNNING.value)
            .filter(SolverJobModel.started_at.is_not(None))
            .filter(SolverJobModel.started_at < running_cutoff)
            .all()
        )

        for job in stale_running:
            job.status = JobStatus.FAILED.value
            job.completed_at = current_time
            job.error_message = (
                "Stale solver job reaped after exceeding the solver timeout window."
            )

        # Sweep 2: orphaned PENDING jobs (never picked up by executor).
        # Strict 30-second UX threshold — if the executor queue is backed up
        # that long, the user gets a clear "high load" message and can retry.
        pending_cutoff = current_time - timedelta(
            seconds=SolverJobStore.PENDING_TIMEOUT_SECONDS,
        )
        orphaned_pending = (
            db.query(SolverJobModel)
            .filter(SolverJobModel.status == JobStatus.PENDING.value)
            .filter(SolverJobModel.created_at < pending_cutoff)
            .all()
        )

        for job in orphaned_pending:
            job.status = JobStatus.FAILED.value
            job.completed_at = current_time
            job.error_message = (
                "Server is currently experiencing high load. Please try again later."
            )

        # Sweep 3: zombie diagnostic statuses (SIGKILL'd diagnostic workers).
        # This uses a guarded UPDATE so the reaper never overwrites a diagnosis
        # that completed after the row was first observed.
        zombie_diag_result = db.execute(
            update(SolverJobModel)
            .where(SolverJobModel.status == JobStatus.FAILED.value)
            .where(SolverJobModel.diagnosis_status.in_(["PENDING", "RUNNING"]))
            .where(SolverJobModel.diagnosis_updated_at.is_not(None))
            .where(SolverJobModel.diagnosis_updated_at < running_cutoff)
            .values(
                diagnosis_status="FAILED",
                diagnosis_message="Diagnostic analysis timed out and was reaped by the stale job reaper.",
                diagnosis_updated_at=current_time,
            )
        )
        zombie_diagnostics_reaped = max(zombie_diag_result.rowcount or 0, 0)

        total_reaped = len(stale_running) + len(orphaned_pending) + zombie_diagnostics_reaped

        if stale_running:
            logger.warning(
                "Reaped %d stale RUNNING solver jobs older than %s",
                len(stale_running),
                running_cutoff.isoformat(),
            )
        if orphaned_pending:
            logger.warning(
                "Reaped %d orphaned PENDING solver jobs created before %s",
                len(orphaned_pending),
                pending_cutoff.isoformat(),
            )
        if zombie_diagnostics_reaped:
            logger.warning(
                "Reaped %d zombie diagnostic statuses older than %s",
                zombie_diagnostics_reaped,
                running_cutoff.isoformat(),
            )

        return total_reaped

    @staticmethod
    def get_latest_completed_job(db: Session, session_id: str) -> Optional[Dict[str, Any]]:
        """Gets the most recent completed job for a session (for Excel export).

        Args:
            db: Active SQLAlchemy session.
            session_id: The session identifier to filter by.

        Returns:
            A dict of job fields for the most recently completed job, or None.
        """
        # Find the most recently finished job (COMPLETED or FAILED) for this
        # session, ordered by completion time descending.  Used by Excel export
        # to retrieve the latest schedule results.
        job = (
            db.query(SolverJobModel)
            .filter_by(session_id=session_id)
            .filter(SolverJobModel.status.in_([JobStatus.COMPLETED.value, JobStatus.FAILED.value]))
            .order_by(SolverJobModel.completed_at.desc())
            .first()
        )
        if not job:
            return None

        # Delegate to get_job() to reuse the ORM→dict conversion logic.
        return SolverJobStore.get_job(db, job.job_id)

    # ─── Async Diagnostic Lifecycle Methods ───────────────────────────
    #
    # State machine: None → PENDING → RUNNING → COMPLETED | FAILED
    #
    # Each method uses an atomic UPDATE...WHERE with the expected current
    # state in the WHERE clause.  This provides single-flight concurrency
    # at the SQL level — no application-level locking needed.
    #
    # All methods commit internally to guarantee immediate persistence and
    # prevent callers from accidentally leaving state transitions uncommitted.

    @staticmethod
    def update_diagnosis_pending(db: Session, job_id: str) -> int:
        """Atomically transitions diagnosis_status: None|FAILED → PENDING.

        Guards: job.status must be FAILED, diagnosis_status must be None or FAILED.
        Allowing FAILED → PENDING enables users to retry diagnostics after a
        crash or timeout without being permanently locked out.
        Commits internally. Clears any stale diagnosis_message from a prior
        attempt and increments diagnosis_attempt to fence off stale callbacks.

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier.

        Returns:
            The new diagnosis_attempt fencing token for this enqueue.

        Raises:
            ValueError: If job not found, not FAILED, or diagnostics already active
                (PENDING, RUNNING, or COMPLETED).
        """
        transition_time = datetime.now(timezone.utc)
        result = db.execute(
            update(SolverJobModel)
            .where(SolverJobModel.job_id == job_id)
            .where(SolverJobModel.status == JobStatus.FAILED.value)
            .where(or_(
                SolverJobModel.diagnosis_status.is_(None),
                SolverJobModel.diagnosis_status == "FAILED",
            ))
            .values(
                diagnosis_status="PENDING",
                diagnosis_message=None,
                diagnosis_attempt=func.coalesce(SolverJobModel.diagnosis_attempt, 0) + 1,
                diagnosis_updated_at=transition_time,
            )
        )
        if result.rowcount == 0:
            db.rollback()
            # Determine failure reason for precise error message
            job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
            if not job:
                raise ValueError(f"Job {job_id} not found")
            if job.status != JobStatus.FAILED.value:
                raise ValueError(
                    f"Job {job_id} not in a failed state (status: {job.status})"
                )
            raise ValueError(
                f"Diagnostics already active for job {job_id} "
                f"(diagnosis_status: {job.diagnosis_status})"
            )
        attempt = db.execute(
            select(SolverJobModel.diagnosis_attempt)
            .where(SolverJobModel.job_id == job_id)
        ).scalar_one()
        db.commit()
        return int(attempt)

    @staticmethod
    def update_diagnosis_running(
        db: Session,
        job_id: str,
        diagnosis_attempt: int,
    ) -> None:
        """Atomically transitions diagnosis_status: PENDING → RUNNING.

        Commits internally.

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier.
            diagnosis_attempt: The attempt token returned by update_diagnosis_pending().

        Raises:
            ValueError: If diagnosis is not in PENDING state.
        """
        result = db.execute(
            update(SolverJobModel)
            .where(SolverJobModel.job_id == job_id)
            .where(SolverJobModel.diagnosis_status == "PENDING")
            .where(SolverJobModel.diagnosis_attempt == diagnosis_attempt)
            .values(
                diagnosis_status="RUNNING",
                diagnosis_updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        if result.rowcount == 0:
            raise ValueError(
                f"Job {job_id} diagnosis is not PENDING — cannot transition to RUNNING"
            )

    @staticmethod
    def update_diagnosis_completed(
        db: Session,
        job_id: str,
        diagnosis_attempt: int,
        message: str,
    ) -> None:
        """Atomically transitions diagnosis_status: RUNNING → COMPLETED.

        Sets diagnosis_message. Commits internally.
        No-op if already terminal (protects against delayed workers).

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier.
            diagnosis_attempt: The attempt token returned by update_diagnosis_pending().
            message: The human-readable diagnosis text.
        """
        result = db.execute(
            update(SolverJobModel)
            .where(SolverJobModel.job_id == job_id)
            .where(SolverJobModel.diagnosis_status == "RUNNING")
            .where(SolverJobModel.diagnosis_attempt == diagnosis_attempt)
            .values(
                diagnosis_status="COMPLETED",
                diagnosis_message=message,
                diagnosis_updated_at=datetime.now(timezone.utc),
            )
        )
        db.commit()
        if result.rowcount == 0:
            logger.warning(
                "update_diagnosis_completed: job %s not in RUNNING state — "
                "possibly already terminal. Skipping overwrite.",
                job_id,
            )

    @staticmethod
    def update_diagnosis_failed(
        db: Session,
        job_id: str,
        diagnosis_attempt: int,
        error_message: str | None = None,
    ) -> None:
        """Atomically transitions diagnosis_status: PENDING|RUNNING → FAILED.

        Commits internally.
        No-op if already terminal (protects against delayed callbacks).

        Args:
            db: Active SQLAlchemy session.
            job_id: The job identifier.
            diagnosis_attempt: The attempt token returned by update_diagnosis_pending().
            error_message: Optional error detail to store in diagnosis_message.
        """
        values: dict = {
            "diagnosis_status": "FAILED",
            "diagnosis_updated_at": datetime.now(timezone.utc),
        }
        if error_message is not None:
            values["diagnosis_message"] = error_message
        result = db.execute(
            update(SolverJobModel)
            .where(SolverJobModel.job_id == job_id)
            .where(SolverJobModel.diagnosis_status.in_(["PENDING", "RUNNING"]))
            .where(SolverJobModel.diagnosis_attempt == diagnosis_attempt)
            .values(**values)
        )
        db.commit()
        if result.rowcount == 0:
            logger.warning(
                "update_diagnosis_failed: job %s not in PENDING/RUNNING state — "
                "possibly already terminal. Skipping overwrite.",
                job_id,
            )
