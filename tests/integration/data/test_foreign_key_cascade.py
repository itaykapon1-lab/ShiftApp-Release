from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data.models import SessionConfigModel, ShiftModel, SolverJobModel, WorkerModel


pytestmark = pytest.mark.integration


def _enable_sqlite_foreign_keys(db_session) -> None:
    db_session.execute(text("PRAGMA foreign_keys = ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_worker_insert_without_parent_session_config_raises_integrity_error(db_session):
    _enable_sqlite_foreign_keys(db_session)

    db_session.add(
        WorkerModel(
            session_id="missing-session-worker",
            worker_id="worker-001",
            name="Orphan Worker",
            attributes={"skills": {"Chef": 5}},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_shift_insert_without_parent_session_config_raises_integrity_error(db_session):
    _enable_sqlite_foreign_keys(db_session)

    db_session.add(
        ShiftModel(
            session_id="missing-session-shift",
            shift_id="shift-001",
            name="Orphan Shift",
            start_time=datetime(2026, 1, 20, 8, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 1, 20, 16, 0, tzinfo=timezone.utc),
            tasks_data={"tasks": []},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_deleting_session_config_cascades_workers_shifts_and_solver_jobs(db_session):
    _enable_sqlite_foreign_keys(db_session)

    session_id = "cascade-session"
    db_session.add(SessionConfigModel(session_id=session_id, constraints=[]))
    db_session.commit()

    db_session.add_all(
        [
            WorkerModel(
                session_id=session_id,
                worker_id="worker-001",
                name="Cascade Worker",
                attributes={"skills": {"Chef": 5}},
            ),
            ShiftModel(
                session_id=session_id,
                shift_id="shift-001",
                name="Cascade Shift",
                start_time=datetime(2026, 1, 20, 8, 0, tzinfo=timezone.utc),
                end_time=datetime(2026, 1, 20, 16, 0, tzinfo=timezone.utc),
                tasks_data={"tasks": []},
            ),
            SolverJobModel(
                job_id="job-001",
                session_id=session_id,
                status="PENDING",
            ),
        ]
    )
    db_session.commit()

    assert db_session.query(SessionConfigModel).filter_by(session_id=session_id).count() == 1
    assert db_session.query(WorkerModel).filter_by(session_id=session_id).count() == 1
    assert db_session.query(ShiftModel).filter_by(session_id=session_id).count() == 1
    assert db_session.query(SolverJobModel).filter_by(session_id=session_id).count() == 1

    config = db_session.query(SessionConfigModel).filter_by(session_id=session_id).one()
    db_session.delete(config)
    db_session.commit()
    db_session.expire_all()

    assert db_session.query(SessionConfigModel).filter_by(session_id=session_id).count() == 0
    assert db_session.query(WorkerModel).filter_by(session_id=session_id).count() == 0
    assert db_session.query(ShiftModel).filter_by(session_id=session_id).count() == 0
    assert db_session.query(SolverJobModel).filter_by(session_id=session_id).count() == 0
