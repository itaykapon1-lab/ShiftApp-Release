"""Performance/architecture acceptance test for solver session efficiency."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm import sessionmaker

import services.solver_service as solver_service
from app.schemas.job import JobStatus
from data.models import SolverJobModel
from services.solver_job_store import SolverJobStore


def test_run_solver_in_process_uses_single_transaction_scope_for_running_to_completed(
    db_session,
    test_session_id,
    monkeypatch,
):
    job_id = SolverJobStore.create_job(db_session, test_session_id)
    engine = db_session.bind
    assert engine is not None

    tracker = {
        "session_creations": 0,
        "commit_calls": 0,
    }

    class TrackingSession(SASession):
        def commit(self):
            tracker["commit_calls"] += 1
            return super().commit()

    tracking_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        class_=TrackingSession,
    )

    def _tracking_session_local():
        tracker["session_creations"] += 1
        return tracking_factory()

    class _FakeSolver:
        def __init__(self, *_args, **_kwargs):
            pass

        def solve(self):
            return {
                "status": "Optimal",
                "objective_value": 99.0,
                "assignments": [{"worker_name": "Alice", "shift_name": "Morning"}],
                "violations": {},
                "theoretical_max_score": 100.0,
                "penalty_breakdown": {},
            }

    monkeypatch.setattr(solver_service, "SessionLocal", _tracking_session_local)
    monkeypatch.setattr(
        solver_service,
        "_prepare_solver_context",
        lambda _db, _session_id: (
            object(),
            object(),
            [SimpleNamespace(name="Alice", worker_id="worker_1")],
            [SimpleNamespace(name="Morning", shift_id="shift_1")],
        ),
    )
    monkeypatch.setattr(solver_service, "ShiftSolver", _FakeSolver)
    monkeypatch.setattr(solver_service, "_print_results", lambda _result: None)

    solver_service.run_solver_in_process(job_id, test_session_id)

    verification_session = tracking_factory()
    try:
        job = verification_session.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job is not None
        assert job.status == JobStatus.COMPLETED.value
        assert job.result_status == "Optimal"
    finally:
        verification_session.close()

    assert tracker["session_creations"] == 1
    assert tracker["commit_calls"] == 1

