"""Repository integration tests for session-level multi-tenant isolation."""

from datetime import datetime

import pytest

from domain.shift_model import Shift
from domain.worker_model import Worker
from repositories.sql_repo import SQLShiftRepository, SQLWorkerRepository
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.integration]


def test_workers_are_isolated_by_session(db_session, id_factory):
    repo_a = SQLWorkerRepository(db_session, "session-a")
    repo_b = SQLWorkerRepository(db_session, "session-b")
    repo_a.add(Worker(name="A", worker_id=id_factory("worker"), skills={"Chef": 5}))
    repo_b.add(Worker(name="B", worker_id=id_factory("worker"), skills={"Driver": 5}))
    db_session.commit()

    assert [w.name for w in repo_a.get_all()] == ["A"]
    assert [w.name for w in repo_b.get_all()] == ["B"]


def test_shifts_are_isolated_by_session(db_session, id_factory):
    repo_a = SQLShiftRepository(db_session, "session-a")
    repo_b = SQLShiftRepository(db_session, "session-b")
    repo_a.add(Shift(name="A", shift_id=id_factory("shift"), time_window=TimeWindow(datetime(2026, 1, 20, 8), datetime(2026, 1, 20, 16))))
    repo_b.add(Shift(name="B", shift_id=id_factory("shift"), time_window=TimeWindow(datetime(2026, 1, 21, 8), datetime(2026, 1, 21, 16))))
    db_session.commit()

    assert [s.name for s in repo_a.get_all()] == ["A"]
    assert [s.name for s in repo_b.get_all()] == ["B"]

