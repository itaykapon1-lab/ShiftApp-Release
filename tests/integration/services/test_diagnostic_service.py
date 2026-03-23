"""Integration tests for DiagnosticService and run_diagnostics_in_process."""

import concurrent.futures
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.constants import SOLVER_STALE_JOB_BUFFER_SECONDS, SOLVER_TIMEOUT_MS
from app.schemas.job import JobStatus
from data.models import SessionConfigModel, ShiftModel, SolverJobModel, WorkerModel
from services.diagnostic_service import DiagnosticService, run_diagnostics_in_process
from services.solver_job_store import SolverJobStore
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


CANONICAL_MONDAY_8AM = datetime(2024, 1, 1, 8, 0)
CANONICAL_MONDAY_4PM = datetime(2024, 1, 1, 16, 0)


def _seed_infeasible_scenario(db, session_id: str) -> str:
    if not db.query(SessionConfigModel).filter_by(session_id=session_id).first():
        db.add(SessionConfigModel(session_id=session_id, constraints=[]))
        db.flush()

    worker_id = f"w_{uuid.uuid4().hex[:8]}"
    db.add(
        WorkerModel(
            session_id=session_id,
            worker_id=worker_id,
            name="Cook_Worker",
            attributes={
                "skills": {"Cook": 5},
                "availability": {
                    "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}
                },
                "wage": 20.0,
                "min_hours": 0,
                "max_hours": 40,
            },
        )
    )

    shift_id = f"s_{uuid.uuid4().hex[:8]}"
    db.add(
        ShiftModel(
            shift_id=shift_id,
            session_id=session_id,
            name="Monday_Surgery",
            start_time=CANONICAL_MONDAY_8AM,
            end_time=CANONICAL_MONDAY_4PM,
            tasks_data={
                "tasks": [
                    {
                        "task_id": f"task_{shift_id}",
                        "name": "Surgery",
                        "options": [
                            {
                                "preference_score": 0,
                                "requirements": [
                                    {
                                        "count": 1,
                                        "required_skills": {"Surgeon": 3},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        )
    )

    job_id = str(uuid.uuid4())
    db.add(
        SolverJobModel(
            job_id=job_id,
            session_id=session_id,
            status=JobStatus.FAILED.value,
            result_status="Infeasible",
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return job_id


def _seed_failed_job_only(db, session_id: str, result_status: str = "Infeasible") -> str:
    if not db.query(SessionConfigModel).filter_by(session_id=session_id).first():
        db.add(SessionConfigModel(session_id=session_id, constraints=[]))
        db.flush()

    job_id = str(uuid.uuid4())
    db.add(
        SolverJobModel(
            job_id=job_id,
            session_id=session_id,
            status=JobStatus.FAILED.value,
            result_status=result_status,
            created_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return job_id


@pytest.fixture(scope="function")
def diag_engine():
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def diag_session_factory(diag_engine):
    return sessionmaker(bind=diag_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def diag_session_id():
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def diag_db(diag_session_factory):
    db = diag_session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.mark.integration
class TestRunDiagnosticsInProcess:
    def test_completes_with_diagnosis_message(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_infeasible_scenario(diag_db, diag_session_id)
        attempt = SolverJobStore.update_diagnosis_pending(diag_db, job_id)

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory), patch(
            "services.solver_service.SessionLocal",
            diag_session_factory,
        ):
            run_diagnostics_in_process(job_id, diag_session_id, attempt)

        diag_db.expire_all()
        job = diag_db.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job.diagnosis_status == "COMPLETED"
        assert job.diagnosis_message
        assert job.diagnosis_attempt == attempt
        assert job.diagnosis_updated_at is not None

    def test_handles_exception_gracefully(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_failed_job_only(diag_db, diag_session_id)
        attempt = SolverJobStore.update_diagnosis_pending(diag_db, job_id)

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory), patch(
            "services.solver_service.SessionLocal",
            diag_session_factory,
        ), patch(
            "services.diagnostic_service._prepare_solver_context",
            side_effect=RuntimeError("boom"),
        ):
            run_diagnostics_in_process(job_id, diag_session_id, attempt)

        diag_db.expire_all()
        job = diag_db.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job.diagnosis_status == "FAILED"
        assert job.diagnosis_attempt == attempt

    def test_does_not_overwrite_terminal_state(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_infeasible_scenario(diag_db, diag_session_id)
        attempt = SolverJobStore.update_diagnosis_pending(diag_db, job_id)
        SolverJobStore.update_diagnosis_running(diag_db, job_id, attempt)
        SolverJobStore.update_diagnosis_failed(diag_db, job_id, attempt)

        SolverJobStore.update_diagnosis_completed(diag_db, job_id, attempt, "late result")

        diag_db.expire_all()
        job = diag_db.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job.diagnosis_status == "FAILED"

    def test_reaper_does_not_overwrite_fresh_worker_completion(
        self,
        diag_session_factory,
        diag_session_id,
    ):
        setup_db = diag_session_factory()
        try:
            job_id = _seed_infeasible_scenario(setup_db, diag_session_id)
            attempt = SolverJobStore.update_diagnosis_pending(setup_db, job_id)
            SolverJobStore.update_diagnosis_running(setup_db, job_id, attempt)

            stale_timestamp = datetime.now(timezone.utc) - timedelta(
                milliseconds=SOLVER_TIMEOUT_MS,
                seconds=SOLVER_STALE_JOB_BUFFER_SECONDS + 5,
            )
            job = setup_db.query(SolverJobModel).filter_by(job_id=job_id).first()
            job.diagnosis_updated_at = stale_timestamp
            setup_db.commit()
        finally:
            setup_db.close()

        worker_db = diag_session_factory()
        try:
            SolverJobStore.update_diagnosis_completed(
                worker_db,
                job_id,
                attempt,
                "fresh worker result",
            )
        finally:
            worker_db.close()

        reaper_db = diag_session_factory()
        try:
            reaped_count = SolverJobStore.reap_stale_jobs(reaper_db)
            reaper_db.commit()
            assert reaped_count == 0
        finally:
            reaper_db.close()

        verify_db = diag_session_factory()
        try:
            job = verify_db.query(SolverJobModel).filter_by(job_id=job_id).first()
            assert job is not None
            assert job.diagnosis_status == "COMPLETED"
            assert job.diagnosis_message == "fresh worker result"
            assert job.diagnosis_attempt == attempt
        finally:
            verify_db.close()


@pytest.mark.integration
class TestDiagnosticServiceOrchestration:
    def test_submits_to_executor_and_returns_job_id(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_infeasible_scenario(diag_db, diag_session_id)

        thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            with patch("services.diagnostic_service.SessionLocal", diag_session_factory), patch(
                "services.solver_service.SessionLocal",
                diag_session_factory,
            ), patch(
                "services.diagnostic_service.get_executor",
                return_value=thread_executor,
            ):
                result = DiagnosticService.start_diagnosis(job_id, diag_session_id)
        finally:
            thread_executor.shutdown(wait=True)

        assert result == job_id

        diag_db.expire_all()
        job = diag_db.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job.diagnosis_status in ("PENDING", "RUNNING", "COMPLETED")
        assert job.diagnosis_attempt == 1

    def test_rejects_non_failed_job(self, diag_session_factory, diag_session_id, diag_db):
        if not diag_db.query(SessionConfigModel).filter_by(session_id=diag_session_id).first():
            diag_db.add(SessionConfigModel(session_id=diag_session_id, constraints=[]))
            diag_db.flush()

        job_id = str(uuid.uuid4())
        diag_db.add(
            SolverJobModel(
                job_id=job_id,
                session_id=diag_session_id,
                status=JobStatus.COMPLETED.value,
                result_status="Optimal",
                created_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
        )
        diag_db.commit()

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory):
            with pytest.raises(ValueError, match="must be Infeasible"):
                DiagnosticService.start_diagnosis(job_id, diag_session_id)

    def test_rejects_non_infeasible_failure(self, diag_session_factory, diag_session_id, diag_db):
        job_id = _seed_failed_job_only(diag_db, diag_session_id, result_status="Timeout")

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory):
            with pytest.raises(ValueError, match="must be Infeasible"):
                DiagnosticService.start_diagnosis(job_id, diag_session_id)

    def test_rejects_pending_solve_job(self, diag_session_factory, diag_session_id, diag_db):
        if not diag_db.query(SessionConfigModel).filter_by(session_id=diag_session_id).first():
            diag_db.add(SessionConfigModel(session_id=diag_session_id, constraints=[]))
            diag_db.flush()

        job_id = str(uuid.uuid4())
        diag_db.add(
            SolverJobModel(
                job_id=job_id,
                session_id=diag_session_id,
                status=JobStatus.PENDING.value,
                created_at=datetime.now(timezone.utc),
            )
        )
        diag_db.commit()

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory):
            with pytest.raises(ValueError, match="must be Infeasible"):
                DiagnosticService.start_diagnosis(job_id, diag_session_id)

    def test_rejects_duplicate_concurrent_run(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_infeasible_scenario(diag_db, diag_session_id)
        SolverJobStore.update_diagnosis_pending(diag_db, job_id)

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory):
            with pytest.raises(ValueError, match="already active"):
                DiagnosticService.start_diagnosis(job_id, diag_session_id)

    def test_marks_failed_on_executor_submit_failure(
        self,
        diag_session_factory,
        diag_session_id,
        diag_db,
    ):
        job_id = _seed_infeasible_scenario(diag_db, diag_session_id)

        class BrokenExecutor:
            def submit(self, *args, **kwargs):
                raise RuntimeError("executor is broken")

        with patch("services.diagnostic_service.SessionLocal", diag_session_factory), patch(
            "services.diagnostic_service.get_executor",
            return_value=BrokenExecutor(),
        ):
            with pytest.raises(RuntimeError, match="executor is broken"):
                DiagnosticService.start_diagnosis(job_id, diag_session_id)

        diag_db.expire_all()
        job = diag_db.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job.diagnosis_status == "FAILED"
        assert job.diagnosis_attempt == 1
