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
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Dict, Any, List, Optional

from sqlalchemy.orm import Session

from app.core.constants import SOLVER_PROCESS_MEMORY_LIMIT_MB
from app.core.config import settings
from app.core.exceptions import ConstraintHydrationError, ResourceConflictError, ShiftAppError, SolverError
from app.db.session import SessionLocal
from data.models import SessionConfigModel
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
from app.utils.date_normalization import is_canonical_date
from app.utils.result_formatter import format_solver_results as _print_results
from services.solver_job_store import SolverJobStore, _serialize_for_json  # noqa: F401 — backward compat re-exports

logger = logging.getLogger(__name__)


# ProcessPoolExecutor for CPU-bound solver work.
# The OR-Tools CP-SAT solver is CPU-intensive and would block the FastAPI async
# event loop if run in-process.  A separate process gives full CPU isolation.
# Lazily initialised by get_executor() on first solve request.
_executor: Optional[concurrent.futures.ProcessPoolExecutor] = None


def _initialize_solver_worker() -> None:
    """Applies best-effort per-process memory limits for solver workers."""
    try:
        import resource
    except ImportError:
        logger.info("Solver worker memory limits unsupported on this platform")
        return

    limit_bytes = SOLVER_PROCESS_MEMORY_LIMIT_MB * 1024 * 1024
    try:
        current_soft, current_hard = resource.getrlimit(resource.RLIMIT_AS)
        hard_limit = current_hard
        if hard_limit in (-1, getattr(resource, "RLIM_INFINITY", -1)):
            hard_limit = limit_bytes
        else:
            hard_limit = min(hard_limit, limit_bytes)
        soft_limit = min(limit_bytes, hard_limit)
        resource.setrlimit(resource.RLIMIT_AS, (soft_limit, hard_limit))
        logger.info(
            "Applied solver worker memory limit: %d MB (previous soft=%s hard=%s)",
            SOLVER_PROCESS_MEMORY_LIMIT_MB,
            current_soft,
            current_hard,
        )
    except (AttributeError, OSError, ValueError) as exc:
        logger.warning("Unable to apply solver worker memory limit: %s", exc)


def _ensure_canonical_temporal_data(all_workers, all_shifts) -> None:
    """Fail fast if solver input contains non-canonical dates."""
    # Scan all shift time windows for dates outside the canonical epoch week
    # (2024-01-01 through 2024-01-07).  Real calendar dates would corrupt the
    # solver's day-of-week logic because the model assumes a fixed Mon–Sun week.
    invalid_shift_windows = []
    for shift in all_shifts:
        start = shift.time_window.start
        end = shift.time_window.end
        if not is_canonical_date(start) or not is_canonical_date(end):
            invalid_shift_windows.append(
                f"shift_id={shift.shift_id} name={shift.name} start={start.isoformat()} end={end.isoformat()}"
            )

    # Scan all worker availability windows for the same invariant.
    # Workers declare availability as a set of TimeWindows; each must be
    # anchored to the canonical epoch so overlap checks are consistent.
    invalid_worker_windows = []
    for worker in all_workers:
        for window in worker.availability:
            if not is_canonical_date(window.start) or not is_canonical_date(window.end):
                invalid_worker_windows.append(
                    f"worker_id={worker.worker_id} name={worker.name} start={window.start.isoformat()} end={window.end.isoformat()}"
                )

    if invalid_shift_windows or invalid_worker_windows:
        # Aggregate up to 5 examples per category to keep error messages readable
        details = []
        if invalid_shift_windows:
            details.append(
                "non-canonical shifts: " + "; ".join(invalid_shift_windows[:5])
            )
        if invalid_worker_windows:
            details.append(
                "non-canonical worker availability: " + "; ".join(invalid_worker_windows[:5])
            )
        # Raise immediately — running the solver with bad dates would produce
        # silently wrong assignments (e.g., Monday workers matched to Sunday shifts).
        raise SolverError(
            safe_message="Solver input contains non-canonical dates.",
            internal_detail=(
                "Canonical Week invariant violation detected before solver execution: "
                + " | ".join(details)
            ),
        )


def _prepare_solver_context(
    db: Session,
    session_id: str,
) -> tuple:
    """Loads domain objects, validates canonical dates, and builds constraint registry.

    Centralises the repeated setup block that appears in both
    ``run_solver_in_process`` and ``run_diagnostics_in_process``.

    Args:
        db: Active SQLAlchemy session.
        session_id: Session identifier for data isolation.

    Returns:
        Tuple of (data_adapter, constraint_registry, all_workers, all_shifts).

    Raises:
        SolverError: If any shift or worker availability window contains a
            non-canonical datetime (Canonical Week invariant violation).
    """
    # Create session-scoped repos that filter all queries by session_id
    # (multi-tenancy isolation — each browser session sees only its own data).
    worker_repo = SQLWorkerRepository(db, session_id=session_id)
    shift_repo = SQLShiftRepository(db, session_id=session_id)

    # Load all domain objects from the DB into memory.  These are pure Python
    # dataclasses (not ORM-bound), so they are safe to pass across process
    # boundaries without triggering SQLAlchemy DetachedInstanceError.
    all_workers = worker_repo.get_all()
    all_shifts = shift_repo.get_all()

    # Fail fast if any datetime falls outside the canonical epoch week.
    _ensure_canonical_temporal_data(all_workers, all_shifts)

    # Hydrate the constraint registry from the SessionConfig JSON stored in DB.
    # This converts persisted JSON blobs → validated Pydantic models → live
    # constraint objects that the solver engine can evaluate.
    constraint_registry = _build_constraint_registry(db, session_id)

    # Wrap the domain objects in a read-only IDataManager adapter that the
    # solver can query without needing a live DB connection.
    data_adapter = SessionDataManagerAdapter(workers=all_workers, shifts=all_shifts)
    return data_adapter, constraint_registry, all_workers, all_shifts


def get_executor() -> concurrent.futures.ProcessPoolExecutor:
    """Lazily initializes the ProcessPoolExecutor."""
    global _executor
    if _executor is None:
        # Create a fixed-size pool capped at settings.solver_max_workers
        # (default: 4).  Each worker process handles one solve job at a time;
        # additional submits queue until a worker becomes free.
        _executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=settings.solver_max_workers,
            initializer=_initialize_solver_worker,
        )
        logger.info("Initialized ProcessPoolExecutor with %d workers", settings.solver_max_workers)
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


def reap_stale_jobs() -> int:
    """Marks stale RUNNING jobs as FAILED during startup recovery."""
    db = SessionLocal()
    try:
        reaped_count = SolverJobStore.reap_stale_jobs(db)
        if reaped_count:
            db.commit()
        else:
            db.rollback()
        logger.info("Startup stale-job sweep reaped %d jobs", reaped_count)
        return reaped_count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_solver_in_process(job_id: str, session_id: str) -> None:
    """Runs the solver in a separate process (or thread).

    Called by ProcessPoolExecutor; creates its own database session so
    DB connections are not shared across process boundaries.
    All SolverJobStore update calls are grouped under one session.

    Args:
        job_id: The job identifier.
        session_id: The session ID for data isolation.
    """
    # Create a NEW DB session for this subprocess.  SQLAlchemy sessions are
    # not safe to share across process boundaries (pickling, connection pool),
    # so each subprocess must open its own connection.
    db: Session = SessionLocal()

    try:
        # 1. Execution-Time UX Threshold (The "Phantom Rule" Fix)
        # If the backend is under heavy load, the job may legitimately wait in the
        # ProcessPoolExecutor queue. If it waits > 30 seconds, we must honor the UX
        # threshold and abort instantly before wasting expensive CPU bounds.
        job_data = SolverJobStore.get_job(db, job_id)
        if not job_data:
            logger.warning("Job %s aborted: not found in database", job_id)
            return
            
        created_at = job_data.get("created_at")
        if created_at:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            wait_time = (datetime.now(timezone.utc) - created_at).total_seconds()
            if wait_time > SolverJobStore.PENDING_TIMEOUT_SECONDS:
                logger.warning(
                    "Job %s aborted: queued for %.1fs (exceeds %ds UX threshold).",
                    job_id, wait_time, SolverJobStore.PENDING_TIMEOUT_SECONDS,
                )
                SolverJobStore.update_job_failed(
                    db=db,
                    job_id=job_id,
                    error_message="Server is currently experiencing high load. Please try again later."
                )
                db.commit()  # Flush the UX failure instantly so the frontend sees it
                return

        # 2. Transition the job from PENDING → RUNNING and record the start timestamp.
        # If the job is no longer PENDING (e.g., cancelled while queued),
        # update_job_running raises ValueError. Abort gracefully.
        try:
            SolverJobStore.update_job_running(db, job_id)
            
            # Fix Ghost RUNNING: We MUST commit this state transition immediately!
            # Otherwise, the DB (and user UI) sees 'PENDING' for the full 30s solve duration,
            # and a C++ segfault will leave the job permanently orphaned in PENDING.
            db.commit()
        except ValueError as exc:
            logger.warning("Job %s aborted: no longer PENDING (%s)", job_id, exc)
            return

        logger.info("[Process] Running solver for job %s, session %s", job_id, session_id)

        # Load domain data, validate canonical dates, and build constraint registry.
        # This is the shared setup block used by both solve and diagnostics paths.
        data_adapter, constraint_registry, all_workers, all_shifts = _prepare_solver_context(db, session_id)

        # Initialize the CP-SAT solver engine with the read-only data adapter
        # and the hydrated constraint registry, then execute the solve.
        solver = ShiftSolver(data_adapter, constraint_registry=constraint_registry)
        result = solver.solve()

        # Log the solver outcome for operational monitoring.
        _print_results(result)
        logger.info("[Process] Solver completed for job %s", job_id)
        logger.info("   Result status: %s", result.get("status"))
        logger.info("   Assignments count: %d", len(result.get("assignments", [])))

        # --- Assignment ID Enrichment ---
        # The solver now emits shift_id directly, but may omit worker_id for
        # legacy code paths.  Here we back-fill any missing IDs so the
        # frontend can link every assignment to specific DB records.
        assignments = result.get("assignments", [])
        if assignments:
            # Build ambiguity-safe name→id lookup: group IDs by name so
            # duplicate names are detected instead of silently overwritten.
            name_to_ids: Dict[str, List[str]] = defaultdict(list)
            for w in all_workers:
                name_to_ids[w.name].append(w.worker_id)
            shift_name_to_ids: Dict[str, List[str]] = defaultdict(list)
            for s in all_shifts:
                shift_name_to_ids[s.name].append(s.shift_id)

            for assign in assignments:
                # Only enrich if the solver did not already set worker_id
                # (legacy solver versions returned name-only assignments).
                if not assign.get('worker_id'):
                    worker_name = assign.get('worker_name')
                    candidates = name_to_ids.get(worker_name, [])
                    if len(candidates) == 1:
                        # Unambiguous: exactly one worker has this name.
                        assign['worker_id'] = candidates[0]
                    elif len(candidates) > 1:
                        # Ambiguous: multiple workers share the same name.
                        # Leave worker_id as None to avoid silent mis-attribution.
                        logger.warning(
                            "Ambiguous legacy assignment: worker_name='%s' maps to %d "
                            "worker_ids %s — leaving worker_id as None",
                            worker_name, len(candidates), candidates,
                        )
                if not assign.get('shift_id'):
                    # Back-fill shift_id by name lookup (same legacy fallback).
                    shift_name = assign.get('shift_name')
                    shift_candidates = shift_name_to_ids.get(shift_name, [])
                    if len(shift_candidates) == 1:
                        assign['shift_id'] = shift_candidates[0]
                    elif len(shift_candidates) > 1:
                        logger.warning(
                            "Ambiguous legacy assignment: shift_name='%s' maps to %d "
                            "shift_ids %s — leaving shift_id as None",
                            shift_name, len(shift_candidates), shift_candidates,
                        )

        # Preflight diagnostics are returned inline by the solver when it
        # detects an obviously infeasible setup (skill gaps, headcount gaps).
        # Full infeasibility diagnosis remains OPT-IN via POST /solve/{job_id}/diagnose.
        diagnosis_message = result.get("diagnosis_message")

        # Persist the solver results to the job record.  All fields (assignments,
        # violations, penalties) are serialised to JSON for storage in the
        # solver_jobs table.
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
        # Commit the COMPLETED results.  The RUNNING state was already committed
        # earlier (Ghost RUNNING fix); this commit persists the final outcome.
        db.commit()

    except Exception as e:
        # Any unhandled error (solver crash, DB issue, canonical-date violation)
        # transitions the job to FAILED.  Full exception details are logged
        # server-side but NEVER persisted to the DB to prevent leaking internal
        # paths, SQL queries, or stack traces to the frontend.
        logger.error("[Process] Job %s failed: %s", job_id, e, exc_info=True)

        # Sanitise the user-facing message: domain exceptions carry a safe_message;
        # all other exceptions get a generic string.
        if isinstance(e, ShiftAppError):
            safe_msg = e.safe_message
        else:
            safe_msg = "The solver encountered an unexpected error."

        # The session may be in an invalid state after a failed commit or flush.
        # A rollback is required before any new queries can be issued.
        try:
            db.rollback()
            SolverJobStore.update_job_failed(db, job_id, safe_msg)
            db.commit()
        except Exception as inner:
            logger.error(
                "Failed to persist FAILED status for job %s: %s",
                job_id, inner,
            )

    finally:
        # Always release the DB connection back to the pool, regardless of
        # success or failure, to prevent connection leaks in the subprocess.
        db.close()


def _load_session_constraints(db: Session, session_id: str) -> list[dict] | None:
    """Loads the constraint JSON list from SessionConfig for a session.

    Args:
        db: Active SQLAlchemy session.
        session_id: The session identifier.

    Returns:
        The constraints list from the SessionConfig row, or None if no
        SessionConfig exists for this session.
    """
    config_model = db.query(SessionConfigModel).filter_by(session_id=session_id).first()
    if not config_model:
        return None
    return config_model.constraints or []


def _build_constraint_registry(db: Session, session_id: str) -> ConstraintRegistry:
    """Builds constraint registry from SessionConfig database using canonical definitions."""
    # Ensure the global category→definition mapping is populated.  In the main
    # FastAPI process this happens at startup, but subprocess workers created by
    # ProcessPoolExecutor start with a fresh Python interpreter, so we must
    # register definitions again.  The ValueError means "already registered" — safe to ignore.
    try:
        register_core_constraints()
    except ValueError:
        # Definitions are already registered in this process.
        pass

    # Start with a fresh registry pre-loaded with hard-coded core constraints
    # (e.g., no-double-booking, shift-coverage).  Session-specific constraints
    # from the DB will be added on top of these.
    registry = ConstraintRegistry()
    registry.add_core_constraints()

    # Load the user's persisted constraint configuration for this session.
    constraints_json = _load_session_constraints(db, session_id)

    if constraints_json is None:
        # No user-configured constraints — return registry with only core constraints.
        logger.info(
            "No SessionConfig found for session %s; using core constraints only",
            session_id,
        )
        return registry

    # Iterate through each persisted constraint entry and hydrate it into a
    # live constraint object that the solver engine can evaluate.
    for idx, item in enumerate(constraints_json):
        # Skip disabled constraints — the user toggled them off in the UI.
        if not item.get("enabled", True):
            continue

        # Look up the canonical definition for this constraint category.
        # The definition provides: Pydantic config model, factory lambda, metadata.
        category = item.get("category")
        try:
            defn = constraint_definitions.get(category)
        except KeyError:
            # Unknown category — possibly from an older schema version or typo.
            logger.info("Unknown constraint category '%s' in SessionConfig (index %d); skipping", category, idx)
            continue

        raw_params = item.get("params")
        params = dict(raw_params) if isinstance(raw_params, dict) else {}
        top_type = item.get("type")  # Top-level "type" field (e.g., "HARD" or "SOFT")

        # Some config models accept `strictness` (e.g. max_hours, dynamic rules),
        # while others do not (e.g. worker_preferences, task_option_priority).
        # Introspect the Pydantic model's declared fields to decide.
        model_has_strictness = "strictness" in defn.config_model.model_fields

        # Drop stray strictness for schemas that do not declare it, preventing
        # Pydantic from raising "unexpected field" validation errors.
        if not model_has_strictness:
            params.pop("strictness", None)

        # Backward-compat bridge: older JSON entries store strictness only at
        # the top-level "type" key, not inside "params".  If the schema expects
        # strictness but params doesn't have it, migrate from top_type.
        if model_has_strictness and "strictness" not in params and isinstance(top_type, str):
            normalized_top = top_type.strip().upper()
            if normalized_top in {"HARD", "SOFT"}:
                params["strictness"] = normalized_top

        # Detect conflicting strictness sources: top-level "type" says HARD but
        # params.strictness says SOFT (or vice versa).  This is ambiguous and
        # likely a data corruption issue — skip rather than guess.
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
                logger.warning(
                    "Constraint strictness mismatch for category '%s' at index %d "
                    "(type=%s, params.strictness=%s); skipping.",
                    category,
                    idx,
                    normalized_top,
                    normalized_param,
                )
                continue

        # Validate params against the Pydantic config model.  This catches
        # invalid types, missing required fields, and out-of-range values.
        try:
            config_obj = defn.config_model.model_validate(params)
        except ValidationError as exc:
            # Determine whether this is a HARD or SOFT constraint.
            # HARD constraint validation failures must abort the solve because
            # running without a required constraint produces incorrect schedules.
            # Check three sources: definition default, params.strictness override,
            # and the top-level "type" field from the persisted JSON.
            effective_type = defn.constraint_type
            param_strictness = params.get("strictness")
            if isinstance(param_strictness, str) and param_strictness.strip().upper() == "HARD":
                effective_type = ConstraintType.HARD
            elif isinstance(top_type, str) and top_type.strip().upper() == "HARD":
                effective_type = ConstraintType.HARD

            if effective_type == ConstraintType.HARD:
                raise ConstraintHydrationError(
                    category=category,
                    detail=(
                        f"HARD constraint '{category}' at index {idx} failed "
                        f"Pydantic validation: {exc}"
                    ),
                )

            logger.warning(
                "Soft constraint '%s' at index %d failed validation: %s; skipping",
                category,
                idx,
                exc,
            )
            continue

        # Use the definition's factory lambda to create a live constraint instance
        # from the validated config, then register it with the solver's registry.
        constraint_instance = defn.factory(config_obj)
        registry.register(constraint_instance)



    logger.info("Constraint Registry built for session %s", session_id)
    return registry


class SolverService:
    """Service for orchestrating solver execution with background tasks."""

    # Only one solve job may be active per session at a time.  This prevents
    # a single user from saturating the ProcessPoolExecutor with concurrent
    # solves (each of which is CPU-intensive and can run for 30+ seconds).
    MAX_JOBS_PER_SESSION = 1

    @staticmethod
    def _has_active_job(db: Session, session_id: str) -> Optional[str]:
        """Check if session has an active (PENDING or RUNNING) job.

        Returns:
            The job_id of the active job if one exists, None otherwise
        """
        return SolverJobStore.get_active_job_id(db, session_id)

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
            ResourceConflictError: If session already has an active job
        """
        # Open a short-lived session just for the pre-flight check and job creation.
        # The actual solve runs in a separate process with its own session.
        db = SessionLocal()
        try:
            # Guard: reject if this session already has a PENDING or RUNNING job.
            # The user must wait for the current job to finish (or fail) before
            # submitting a new one.  This maps to MAX_JOBS_PER_SESSION=1.
            active_job_id = SolverService._has_active_job(db, session_id)
            if active_job_id:
                raise ResourceConflictError(
                    safe_message=(
                        f"Session already has an active job ({active_job_id}). "
                        f"Please wait for it to complete or check its status."
                    )
                )

            # Insert a new job row in PENDING state (flush only — not yet
            # committed).  The row is visible to queries on this session but
            # not to other connections until we commit.
            job_id = SolverJobStore.create_job(db, session_id)

            # Post-insert race detection (Optimistic Concurrency Control):
            # If two requests bypassed the _has_active_job() check simultaneously,
            # both will have flushed a PENDING job.  A COUNT query on this
            # session detects the duplicate.  The losing request rolls back
            # (discarding the flushed row) and raises ResourceConflictError.
            active_count = SolverJobStore.count_active_jobs(db, session_id)
            if active_count > SolverService.MAX_JOBS_PER_SESSION:
                db.rollback()
                raise ResourceConflictError(
                    safe_message=(
                        "Session already has an active job. "
                        "Please wait for it to complete or check its status."
                    )
                )

            # Race check passed — commit the job so the frontend can poll it
            # and the subprocess can see it via its own session.
            db.commit()
        finally:
            db.close()

        # Hand off the CPU-bound solve to the ProcessPoolExecutor.
        # The executor.submit() call returns immediately (non-blocking);
        # run_solver_in_process will create its own DB session in the subprocess.
        executor = get_executor()
        try:
            future = executor.submit(run_solver_in_process, job_id, session_id)
        except Exception as submit_exc:
            # BrokenProcessPool or other fatal pool error — the job was already
            # committed as PENDING but will never be picked up.  Mark it FAILED
            # immediately so the session is not permanently blocked.
            logger.error(
                "Failed to submit job %s to executor: %s",
                job_id, submit_exc, exc_info=True,
            )
            fail_db = SessionLocal()
            try:
                SolverJobStore.update_job_failed(
                    fail_db, job_id, "Solver pool unavailable.",
                )
                fail_db.commit()
            except Exception as inner:
                logger.error(
                    "Failed to mark job %s as FAILED after submit failure: %s",
                    job_id, inner,
                )
            finally:
                fail_db.close()
            raise

        def _on_done(f) -> None:
            try:
                f.result()
            except Exception as e:
                # Catches BrokenProcessPool or other unhandled executor crashes
                # (e.g. SIGKILL).  Only a generic message is persisted — the full
                # exception is logged server-side to prevent information leakage.
                logger.error(
                    "Solver process for job %s terminated unexpectedly: %s",
                    job_id, e, exc_info=True,
                )
                db = SessionLocal()
                try:
                    SolverJobStore.update_job_failed(
                        db, job_id,
                        "The solver process terminated unexpectedly.",
                    )
                    db.commit()
                except Exception as inner_e:
                    logger.error(
                        "Failed to mark job %s as failed after process crash: %s",
                        job_id, inner_e,
                    )
                finally:
                    db.close()

        future.add_done_callback(_on_done)

        logger.info("Submitted job %s to ProcessPoolExecutor", job_id)
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
            # Security: multi-tenancy guard.  A user should only be able to
            # view jobs belonging to their own session.  If session_id is
            # provided and doesn't match, treat the job as "not found".
            if job_data and session_id and job_data.get("session_id") != session_id:
                logger.warning("Session %s attempted to access job %s belonging to different session", session_id, job_id)
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

