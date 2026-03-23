"""Diagnostic Service — async infeasibility analysis.

Extracts diagnostic orchestration from SolverService to prevent God Class growth.
Runs diagnostics in the shared ProcessPoolExecutor, polling via GET /status/{job_id}.
"""

import logging

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from services.solver_job_store import SolverJobStore
from services.solver_service import _prepare_solver_context, get_executor
from solver.solver_engine import ShiftSolver

logger = logging.getLogger(__name__)


def run_diagnostics_in_process(
    job_id: str,
    session_id: str,
    diagnosis_attempt: int,
) -> None:
    """Background worker for diagnostic analysis. Runs in ProcessPoolExecutor.

    Mirrors run_solver_in_process pattern: fresh SessionLocal, atomic state
    transitions, try/except/rollback/finally.

    State machine: PENDING -> RUNNING -> COMPLETED | FAILED
    All transitions use atomic UPDATE...WHERE (internal commits in store methods).
    """
    db: Session = SessionLocal()
    try:
        # Atomic: PENDING -> RUNNING (commits internally via store method)
        SolverJobStore.update_diagnosis_running(db, job_id, diagnosis_attempt)

        # Load domain data, validate canonical dates, hydrate constraint registry.
        data_adapter, constraint_registry, _, _ = _prepare_solver_context(db, session_id)

        # Run the 4-stage infeasibility diagnosis (CPU-heavy: preflight ->
        # base model -> individual constraints -> constraint stacking).
        solver = ShiftSolver(data_adapter, constraint_registry=constraint_registry)
        diagnosis_message = solver.diagnose_infeasibility()

        # Atomic: RUNNING -> COMPLETED + persist message (commits internally).
        # No-op if already terminal (e.g., done callback already marked FAILED).
        SolverJobStore.update_diagnosis_completed(
            db,
            job_id,
            diagnosis_attempt,
            diagnosis_message,
        )
        logger.info("Diagnostics completed for job %s: %.100s...", job_id, diagnosis_message)

    except Exception as e:
        logger.error("Diagnostics for job %s failed: %s", job_id, e, exc_info=True)
        try:
            db.rollback()
            # Atomic: PENDING|RUNNING -> FAILED (commits internally).
            # No-op if already terminal.
            SolverJobStore.update_diagnosis_failed(db, job_id, diagnosis_attempt)
        except Exception as inner:
            logger.error("Failed to persist FAILED diagnosis for job %s: %s", job_id, inner)
    finally:
        db.close()


class DiagnosticService:
    """Async diagnostic orchestration — companion to SolverService.

    Responsibilities:
    - Validates preconditions (job is FAILED, no active diagnostics)
    - Sets diagnosis_status=PENDING
    - Submits run_diagnostics_in_process to shared ProcessPoolExecutor
    - Attaches crash-recovery done callback
    """

    @staticmethod
    def start_diagnosis(job_id: str, session_id: str) -> str:
        """Enqueues diagnostic analysis for a failed solver job.

        Returns immediately after setting diagnosis_status=PENDING and submitting
        to the ProcessPoolExecutor.

        Args:
            job_id: The solver job to diagnose.
            session_id: Session ID for multi-tenancy isolation.

        Returns:
            The job_id (same as input — for API response).

        Raises:
            ValueError: If job not found, not FAILED, or diagnostics already active.
        """
        db = SessionLocal()
        try:
            # Validate job exists and belongs to session.
            job_data = SolverJobStore.get_job(db, job_id)
            if not job_data or job_data.get("session_id") != session_id:
                raise ValueError(f"Job {job_id} not found")

            if job_data.get("result_status") != "Infeasible":
                raise ValueError(
                    f"Job {job_id} result_status must be Infeasible for diagnostics "
                    f"(got: {job_data.get('result_status')})"
                )

            # Atomic: None|FAILED -> PENDING (commits internally).
            # Raises ValueError if job not FAILED or diagnosis already active.
            diagnosis_attempt = SolverJobStore.update_diagnosis_pending(db, job_id)
        finally:
            db.close()

        # Submit to shared ProcessPoolExecutor.
        executor = get_executor()
        try:
            future = executor.submit(
                run_diagnostics_in_process,
                job_id,
                session_id,
                diagnosis_attempt,
            )
        except Exception as submit_exc:
            logger.error("Failed to submit diagnostics for job %s: %s", job_id, submit_exc)
            fail_db = SessionLocal()
            try:
                SolverJobStore.update_diagnosis_failed(
                    fail_db,
                    job_id,
                    diagnosis_attempt,
                )
            except Exception:
                pass
            finally:
                fail_db.close()
            raise

        def _on_diag_done(f):
            """Crash-recovery callback: if the process dies, mark FAILED."""
            try:
                f.result()
            except Exception as e:
                logger.error("Diagnostics process for job %s crashed: %s", job_id, e)
                crash_db = SessionLocal()
                try:
                    SolverJobStore.update_diagnosis_failed(
                        crash_db,
                        job_id,
                        diagnosis_attempt,
                    )
                except Exception:
                    pass
                finally:
                    crash_db.close()

        future.add_done_callback(_on_diag_done)
        return job_id
