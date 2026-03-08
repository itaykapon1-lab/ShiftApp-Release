"""Architecture-level unit tests for SolverJobStore session usage and status mapping."""

from __future__ import annotations

import app.db.session as db_session_module
import services.solver_job_store as job_store_module
from app.schemas.job import JobStatus
from data.models import SolverJobModel
from services.solver_job_store import SolverJobStore


def _forbid_sessionlocal(*_args, **_kwargs):
    raise AssertionError("SessionLocal must not be called by SolverJobStore update methods")


def _patch_all_session_factories(monkeypatch) -> None:
    # Guard both the local module path and the canonical db module path.
    monkeypatch.setattr(job_store_module, "SessionLocal", _forbid_sessionlocal, raising=False)
    monkeypatch.setattr(db_session_module, "SessionLocal", _forbid_sessionlocal, raising=False)


def test_update_job_running_uses_explicit_db_session_only(
    db_session,
    test_session_id,
    monkeypatch,
):
    job_id = SolverJobStore.create_job(db_session, test_session_id)
    _patch_all_session_factories(monkeypatch)
    counter = {"commit_calls": 0}
    real_commit = db_session.commit

    def _tracked_commit():
        counter["commit_calls"] += 1
        return real_commit()

    monkeypatch.setattr(db_session, "commit", _tracked_commit)

    SolverJobStore.update_job_running(db_session, job_id)
    db_session.commit()  # caller owns the commit (Unit of Work)

    assert counter["commit_calls"] == 1
    db_session.expire_all()
    job = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
    assert job is not None
    assert job.status == JobStatus.RUNNING.value
    assert job.started_at is not None


def test_update_job_completed_uses_explicit_db_session_only(
    db_session,
    test_session_id,
    monkeypatch,
):
    job_id = SolverJobStore.create_job(db_session, test_session_id)
    _patch_all_session_factories(monkeypatch)
    counter = {"commit_calls": 0}
    real_commit = db_session.commit

    def _tracked_commit():
        counter["commit_calls"] += 1
        return real_commit()

    monkeypatch.setattr(db_session, "commit", _tracked_commit)

    SolverJobStore.update_job_completed(
        db=db_session,
        job_id=job_id,
        result_status="Optimal",
        objective_value=123.0,
        assignments=[{"worker_name": "Alice", "shift_name": "AM"}],
        violations={"coverage": []},
    )
    db_session.commit()  # caller owns the commit (Unit of Work)

    assert counter["commit_calls"] == 1
    db_session.expire_all()
    job = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
    assert job is not None
    assert job.status == JobStatus.COMPLETED.value
    assert job.result_status == "Optimal"
    assert job.objective_value == 123.0


def test_update_job_failed_uses_explicit_db_session_only(
    db_session,
    test_session_id,
    monkeypatch,
):
    job_id = SolverJobStore.create_job(db_session, test_session_id)
    _patch_all_session_factories(monkeypatch)
    counter = {"commit_calls": 0}
    real_commit = db_session.commit

    def _tracked_commit():
        counter["commit_calls"] += 1
        return real_commit()

    monkeypatch.setattr(db_session, "commit", _tracked_commit)

    SolverJobStore.update_job_failed(db_session, job_id, "boom")
    db_session.commit()  # caller owns the commit (Unit of Work)

    assert counter["commit_calls"] == 1
    db_session.expire_all()
    job = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
    assert job is not None
    assert job.status == JobStatus.FAILED.value
    assert job.error_message == "boom"


def test_update_job_completed_maps_infeasible_to_failed(db_session, test_session_id):
    job_id = SolverJobStore.create_job(db_session, test_session_id)

    SolverJobStore.update_job_completed(
        db=db_session,
        job_id=job_id,
        result_status="Infeasible",
        objective_value=0.0,
        assignments=[],
        violations={},
    )
    db_session.commit()  # caller owns the commit (Unit of Work)

    db_session.expire_all()
    job = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
    assert job is not None
    assert job.status == JobStatus.FAILED.value
    assert job.result_status == "Infeasible"
