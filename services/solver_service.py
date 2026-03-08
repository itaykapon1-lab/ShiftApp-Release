"""Solver Service Layer.

This module orchestrates the solver execution with:
- Database-backed job store (replaces in-memory _job_store)
- ProcessPoolExecutor for CPU isolation (prevents blocking)
- Proper database session management for background workers

SCALING CHANGES (v2.0):
- Jobs are persisted to `solver_jobs` table for multi-worker visibility
- Solver runs in a separate PROCESS to avoid blocking the event loop
- Works with both SQLite (local dev) and PostgreSQL (production)
"""

import atexit
import logging
import uuid
import asyncio
import concurrent.futures
from datetime import date, datetime
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from data.models import SessionConfigModel, SolverJobModel
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository
from services.session_adapter import SessionDataManagerAdapter
from solver.solver_engine import ShiftSolver
from solver.constraints.registry import ConstraintRegistry
from solver.constraints.base import ConstraintType
from solver.constraints.definitions import (
    constraint_definitions,
    register_core_constraints,
)
from pydantic import ValidationError
from app.schemas.job import JobStatus
from app.utils.date_normalization import is_canonical_date
from app.utils.result_formatter import format_solver_results as _print_results
from services.solver_job_store import SolverJobStore, _serialize_for_json  # noqa: F401 — backward compat re-exports

logger = logging.getLogger(__name__)


# ProcessPoolExecutor for CPU-bound solver work
# This prevents the solver from blocking the FastAPI event loop
_executor: Optional[concurrent.futures.ProcessPoolExecutor] = None


def _ensure_canonical_temporal_data(all_workers, all_shifts) -> None:
    """Fail fast if solver input contains non-canonical dates."""
    invalid_shift_windows = []
    for shift in all_shifts:
        start = shift.time_window.start
        end = shift.time_window.end
        if not is_canonical_date(start) or not is_canonical_date(end):
            invalid_shift_windows.append(
                f"shift_id={shift.shift_id} name={shift.name} start={start.isoformat()} end={end.isoformat()}"
            )

    invalid_worker_windows = []
    for worker in all_workers:
        for window in worker.availability:
            if not is_canonical_date(window.start) or not is_canonical_date(window.end):
                invalid_worker_windows.append(
                    f"worker_id={worker.worker_id} name={worker.name} start={window.start.isoformat()} end={window.end.isoformat()}"
                )

    if invalid_shift_windows or invalid_worker_windows:
        details = []
        if invalid_shift_windows:
            details.append(
                "non-canonical shifts: " + "; ".join(invalid_shift_windows[:5])
            )
        if invalid_worker_windows:
            details.append(
                "non-canonical worker availability: " + "; ".join(invalid_worker_windows[:5])
            )
        raise ValueError(
            "Canonical Week invariant violation detected before solver execution: "
            + " | ".join(details)
        )


def _prepare_solver_context(
    db: Session,
    session_id: str,
) -> tuple:
    """Loads domain objects, validates canonical dates, and builds constraint registry.

    Centralises the repeated setup block that appears in both
    ``run_solver_in_process`` and ``SolverService.run_diagnostics``.

    Args:
        db: Active SQLAlchemy session.
        session_id: Session identifier for data isolation.

    Returns:
        Tuple of (data_adapter, constraint_registry, all_workers, all_shifts).

    Raises:
        ValueError: If any shift or worker availability window contains a
            non-canonical datetime (Canonical Week invariant violation).
    """
    worker_repo = SQLWorkerRepository(db, session_id=session_id)
    shift_repo = SQLShiftRepository(db, session_id=session_id)
    all_workers = worker_repo.get_all()
    all_shifts = shift_repo.get_all()
    _ensure_canonical_temporal_data(all_workers, all_shifts)
    constraint_registry = _build_constraint_registry(db, session_id)
    data_adapter = SessionDataManagerAdapter(workers=all_workers, shifts=all_shifts)
    return data_adapter, constraint_registry, all_workers, all_shifts


def get_executor() -> concurrent.futures.ProcessPoolExecutor:
    """Lazily initializes the ProcessPoolExecutor."""
    global _executor
    if _executor is None:
        _executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=settings.solver_max_workers
        )
        logger.info(f"Initialized ProcessPoolExecutor with {settings.solver_max_workers} workers")
    return _executor


def _shutdown_executor() -> None:
    """Cleanly terminates the ProcessPoolExecutor on interpreter exit.

    Registered with ``atexit`` to ensure no worker processes are orphaned
    when the FastAPI application shuts down.  Teardown exceptions are caught
    and logged rather than propagated so that ``_executor`` is always cleared.
    """
    global _executor
    if _executor is not None:
        logger.info("Shutting down ProcessPoolExecutor...")
        try:
            _executor.shutdown(wait=True)
        except Exception as exc:
            logger.error("ProcessPoolExecutor shutdown raised an error: %s", exc)
        finally:
            _executor = None


atexit.register(_shutdown_executor)


def run_solver_in_process(job_id: str, session_id: str) -> None:
    """Runs the solver in a separate process (or thread).

    Called by ProcessPoolExecutor; creates its own database session so
    DB connections are not shared across process boundaries.
    All SolverJobStore update calls are grouped under one session.

    Args:
        job_id: The job identifier.
        session_id: The session ID for data isolation.
    """
    # Create a single DB session for the entire subprocess lifetime.
    db: Session = SessionLocal()

    try:
        SolverJobStore.update_job_running(db, job_id)

        logger.info(f"[Process] Running solver for job {job_id}, session {session_id}")

        data_adapter, constraint_registry, all_workers, all_shifts = _prepare_solver_context(db, session_id)

        # Initialize and run solver
        solver = ShiftSolver(data_adapter, constraint_registry=constraint_registry)
        result = solver.solve()

        # Log results
        _print_results(result)
        logger.info(f"[Process] Solver completed for job {job_id}")
        logger.info(f"   Result status: {result.get('status')}")
        logger.info(f"   Assignments count: {len(result.get('assignments', []))}")

        # Enrich assignments with IDs
        assignments = result.get("assignments", [])
        if assignments:
            worker_name_to_id = {w.name: w.worker_id for w in all_workers}
            shift_name_to_id = {s.name: s.shift_id for s in all_shifts}

            for assign in assignments:
                worker_name = assign.get('worker_name')
                shift_name = assign.get('shift_name')

                assign['worker_id'] = worker_name_to_id.get(worker_name)
                assign['shift_id'] = shift_name_to_id.get(shift_name)

        # Diagnostics are now OPT-IN: User must trigger via POST /solve/{job_id}/diagnose
        # This improves UX by not auto-running expensive diagnostics on every failure
        diagnosis_message = None

        # Update job with results — same session, no extra connection needed.
        SolverJobStore.update_job_completed(
            db=db,
            job_id=job_id,
            result_status=result.get("status"),
            objective_value=result.get("objective_value", 0),
            assignments=assignments,
            violations=result.get("violations", {}),
            theoretical_max_score=result.get("theoretical_max_score"),
            diagnosis_message=diagnosis_message,
            penalty_breakdown=result.get("penalty_breakdown", {}),
        )
        # Single commit for the entire success path (Unit of Work).
        db.commit()

    except Exception as e:
        logger.error(f"[Process] Job {job_id} failed: {e}", exc_info=True)
        SolverJobStore.update_job_failed(db, job_id, str(e))
        db.commit()

    finally:
        db.close()


def _build_constraint_registry(db: Session, session_id: str) -> ConstraintRegistry:
    """Builds constraint registry from SessionConfig database using canonical definitions."""
    # Ensure category->definition mapping exists in every process context.
    try:
        register_core_constraints()
    except ValueError:
        # Definitions are already registered in this process.
        pass

    registry = ConstraintRegistry()
    registry.add_core_constraints()


    config_model = db.query(SessionConfigModel).filter_by(session_id=session_id).first()

    if not config_model:
        logger.warning(
            "No SessionConfig found for session %s; no persisted constraints to load",
            session_id,
        )
        return registry

    constraints_json = config_model.constraints or []

    for idx, item in enumerate(constraints_json):
        if not item.get("enabled", True):
            continue

        category = item.get("category")
        try:
            defn = constraint_definitions.get(category)
        except KeyError:
            logger.warning("Unknown constraint category '%s' in SessionConfig (index %d); skipping", category, idx)
            continue

        raw_params = item.get("params")
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        top_type = item.get("type")

        # Some config models accept `strictness` (e.g. max_hours, dynamic rules),
        # while others do not (e.g. worker_preferences, task_option_priority).
        # Keep top-level `type` as a backward-compat source only when schema allows it.
        model_has_strictness = "strictness" in defn.config_model.model_fields

        # Drop stray strictness for schemas that do not declare it.
        if not model_has_strictness:
            params.pop("strictness", None)

        # Backward-compat bridge: if strictness exists only at top level,
        # inject it into params before schema validation.
        if model_has_strictness and "strictness" not in params and isinstance(top_type, str):
            normalized_top = top_type.strip().upper()
            if normalized_top in {"HARD", "SOFT"}:
                params["strictness"] = normalized_top

        # Detect conflicting strictness sources and skip ambiguous constraints.
        if model_has_strictness and isinstance(top_type, str) and "strictness" in params:
            normalized_top = top_type.strip().upper()
            raw_param_strictness = params.get("strictness")
            normalized_param = None
            if isinstance(raw_param_strictness, str):
                normalized_param = raw_param_strictness.strip().upper()
            elif isinstance(raw_param_strictness, ConstraintType):
                normalized_param = raw_param_strictness.value.upper()

            if (
                normalized_top in {"HARD", "SOFT"}
                and normalized_param in {"HARD", "SOFT"}
                and normalized_top != normalized_param
            ):
                logger.error(
                    "Constraint strictness mismatch for category '%s' at index %d "
                    "(type=%s, params.strictness=%s); skipping.",
                    category,
                    idx,
                    normalized_top,
                    normalized_param,
                )
                continue

        try:
            config_obj = defn.config_model.model_validate(params)
        except ValidationError as exc:
            logger.error(
                "Constraint validation failed for category '%s' at index %d: %s",
                category,
                idx,
                exc,
            )
            continue

        constraint_instance = defn.factory(config_obj)
        registry.register(constraint_instance)



    logger.info(f"Constraint Registry built for session {session_id}")
    return registry


class SolverService:
    """Service for orchestrating solver execution with background tasks."""

    # Maximum concurrent jobs per session to prevent resource exhaustion
    MAX_JOBS_PER_SESSION = 1

    @staticmethod
    def _has_active_job(db: Session, session_id: str) -> Optional[str]:
        """Check if session has an active (PENDING or RUNNING) job.

        Returns:
            The job_id of the active job if one exists, None otherwise
        """
        active_job = (
            db.query(SolverJobModel)
            .filter_by(session_id=session_id)
            .filter(SolverJobModel.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]))
            .first()
        )
        return active_job.job_id if active_job else None

    @staticmethod
    def start_job(
        session_id: str,
        background_tasks=None  # Optional for backward compatibility
    ) -> str:
        """
        Starts a new solve job using ProcessPoolExecutor.

        Args:
            session_id: The session ID for data isolation
            background_tasks: (Deprecated) FastAPI background tasks - not used

        Returns:
            str: The job ID

        Raises:
            ValueError: If session already has an active job
        """
        db = SessionLocal()
        try:
            # Check for existing active job to prevent resource exhaustion
            active_job_id = SolverService._has_active_job(db, session_id)
            if active_job_id:
                raise ValueError(
                    f"Session already has an active job ({active_job_id}). "
                    f"Please wait for it to complete or check its status."
                )

            # Create job in database
            job_id = SolverJobStore.create_job(db, session_id)
        finally:
            db.close()

        # Submit to ProcessPoolExecutor
        executor = get_executor()
        executor.submit(run_solver_in_process, job_id, session_id)

        logger.info(f"Submitted job {job_id} to ProcessPoolExecutor")
        return job_id

    @staticmethod
    def run_solver_background(job_id: str, session_id: str) -> None:
        """
        Legacy method for backward compatibility.
        Now delegates to run_solver_in_process.
        """
        run_solver_in_process(job_id, session_id)

    @staticmethod
    def get_job_status(job_id: str, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves the status of a job from the database.

        Args:
            job_id: The job identifier
            session_id: Optional session ID to validate ownership (security filter)

        Returns:
            Dict with job status information, or None if job not found or access denied
        """
        db = SessionLocal()
        try:
            job_data = SolverJobStore.get_job(db, job_id)
            # Security: If session_id provided, validate job belongs to that session
            if job_data and session_id and job_data.get("session_id") != session_id:
                logger.warning(f"Session {session_id} attempted to access job {job_id} belonging to different session")
                return None
            return job_data
        finally:
            db.close()

    @staticmethod
    def get_latest_job_for_session(session_id: str) -> Optional[Dict[str, Any]]:
        """
        Gets the latest completed job for a session (for Excel export).

        Args:
            session_id: The session ID

        Returns:
            Dict with job data, or None if no completed jobs
        """
        db = SessionLocal()
        try:
            return SolverJobStore.get_latest_completed_job(db, session_id)
        finally:
            db.close()

    @staticmethod
    def run_diagnostics(job_id: str, session_id: str) -> str:
        """
        Runs diagnostics for a failed solver job (OPT-IN).

        This is called on-demand when the user clicks "Run Diagnostics"
        rather than automatically on every failure.

        Args:
            job_id: The job identifier
            session_id: The session ID for data isolation

        Returns:
            str: The diagnosis message explaining the failure
        """
        db: Session = SessionLocal()

        try:
            data_adapter, constraint_registry, _, _ = _prepare_solver_context(db, session_id)

            # Initialize solver and run diagnostics
            solver = ShiftSolver(data_adapter, constraint_registry=constraint_registry)
            diagnosis_message = solver.diagnose_infeasibility()

            # Update job with diagnosis result
            job = db.query(SolverJobModel).filter_by(job_id=job_id).first()
            if job:
                job.diagnosis_message = diagnosis_message
                db.commit()

            logger.info(f"Diagnostics completed for job {job_id}: {diagnosis_message[:100]}...")
            return diagnosis_message

        except Exception as e:
            logger.error(f"Diagnostics failed for job {job_id}: {e}", exc_info=True)
            return f"Unable to determine cause: {str(e)}"

        finally:
            db.close()
