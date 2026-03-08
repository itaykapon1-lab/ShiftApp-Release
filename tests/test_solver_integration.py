"""Solver integration tests for DB->registry->engine constraint application."""

from __future__ import annotations

import os
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from data.base import Base
from data.models import SessionConfigModel
from domain.shift_model import Shift
from domain.task_model import Task, TaskOption
from domain.worker_model import Worker
from repositories.sql_repo import SQLShiftRepository, SQLWorkerRepository
from services.excel_service import ExcelService
from services.session_adapter import SessionDataManagerAdapter
from services.solver_service import _build_constraint_registry
from solver.constraints.dynamic import MutualExclusionConstraint
from solver.solver_engine import ShiftSolver
from domain.time_utils import TimeWindow


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def test_session_id():
    return "solver-integration-session"


def _make_shift(shift_id: str, name: str, start: datetime, end: datetime, required_count: int = 1) -> Shift:
    shift = Shift(name=name, shift_id=shift_id, time_window=TimeWindow(start, end))
    task = Task(name=f"{name}-task")
    option = TaskOption(preference_score=0)
    option.add_requirement(count=required_count, required_skills={"Service": 3})
    task.add_option(option)
    shift.add_task(task)
    return shift


def _run_solver(db, session_id: str):
    worker_repo = SQLWorkerRepository(db, session_id=session_id)
    shift_repo = SQLShiftRepository(db, session_id=session_id)

    workers = worker_repo.get_all()
    shifts = shift_repo.get_all()
    registry = _build_constraint_registry(db, session_id)

    data_adapter = SessionDataManagerAdapter(workers=workers, shifts=shifts)
    solver = ShiftSolver(data_adapter, constraint_registry=registry)
    result = solver.solve()
    return result, registry, workers


def _assignments_by_shift_worker_id(result: dict, workers: list[Worker]) -> dict[str, set[str]]:
    worker_name_to_id = {w.name: w.worker_id for w in workers}
    by_shift: dict[str, set[str]] = {}
    for row in result.get("assignments", []):
        shift_name = row.get("shift_name")
        worker_name = row.get("worker_name")
        if not shift_name or not worker_name:
            continue
        wid = worker_name_to_id.get(worker_name)
        if not wid:
            continue
        by_shift.setdefault(shift_name, set()).add(wid)
    return by_shift


def test_excel_to_solver_execution(db_session, test_session_id):
    """E2E: Excel import -> registry load -> solver enforces mutual exclusion."""
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    excel_path = os.path.join(base_path, "Grand_Hotel_Gen_Chaos.xlsx")
    if not os.path.exists(excel_path):
        pytest.skip(f"Grand Hotel file not found: {excel_path}")

    excel_service = ExcelService(db_session, test_session_id)
    with open(excel_path, "rb") as f:
        excel_service.import_excel(f.read())
    db_session.commit()

    result, registry, workers = _run_solver(db_session, test_session_id)

    # ASSERTION 1 (Registry): more than core constraints and has dynamic bans.
    assert len(registry._constraints) > 3
    assert any(c.name.startswith("ban_") for c in registry._constraints)

    config = db_session.query(SessionConfigModel).filter_by(session_id=test_session_id).first()
    assert config is not None
    mutual_exclusions = [c for c in (config.constraints or []) if c.get("category") == "mutual_exclusion"]
    assert len(mutual_exclusions) > 0

    # ASSERTION 2 (Logic): banned workers are not together in same shift.
    assigned = _assignments_by_shift_worker_id(result, workers)
    for c in mutual_exclusions:
        params = c.get("params", {})
        wa = params.get("worker_a_id")
        wb = params.get("worker_b_id")
        if not wa or not wb:
            continue
        for shift_workers in assigned.values():
            assert not ({wa, wb} <= shift_workers), f"Mutual exclusion violated for {wa}/{wb}"


def test_manual_api_to_solver_execution(db_session, test_session_id, caplog):
    """Manual config in DB should be applied by solver and not skipped."""
    worker_repo = SQLWorkerRepository(db_session, session_id=test_session_id)
    shift_repo = SQLShiftRepository(db_session, session_id=test_session_id)

    start = datetime(2026, 2, 16, 8, 0, 0)
    end = datetime(2026, 2, 16, 16, 0, 0)

    for worker_id, name in [("W_A", "Alice"), ("W_B", "Bob"), ("W_C", "Charlie")]:
        w = Worker(name=name, worker_id=worker_id, min_hours=0, max_hours=40, wage=10.0)
        w.set_skill_level("Service", 5)
        w.add_availability(datetime(2026, 2, 16, 6, 0, 0), datetime(2026, 2, 16, 20, 0, 0))
        worker_repo.add(w)

    shift_repo.add(_make_shift("S_1", "Morning", start, end, required_count=2))

    db_session.add(
        SessionConfigModel(
            session_id=test_session_id,
            constraints=[
                {
                    "id": 1,
                    "category": "mutual_exclusion",
                    "type": "HARD",
                    "enabled": True,
                    "params": {
                        "worker_a_id": "W_A",
                        "worker_b_id": "W_B",
                        "strictness": "HARD",
                        "penalty": -100.0,
                    },
                }
            ],
        )
    )
    db_session.commit()

    caplog.set_level("WARNING")
    result, registry, workers = _run_solver(db_session, test_session_id)

    # Should be mapped and registered, not skipped as unknown category.
    assert any(isinstance(c, MutualExclusionConstraint) for c in registry._constraints)
    assert "Unknown constraint category 'mutual_exclusion'" not in caplog.text

    assigned = _assignments_by_shift_worker_id(result, workers)
    for shift_workers in assigned.values():
        assert not ({"W_A", "W_B"} <= shift_workers)


def test_constraint_registry_mapping(db_session, test_session_id):
    """Unit-ish: DB JSON category keys map to concrete constraint instances."""
    db_session.add(
        SessionConfigModel(
            session_id=test_session_id,
            constraints=[
                {
                    "id": 1,
                    "category": "max_hours_per_week",
                    "type": "SOFT",
                    "enabled": True,
                    "params": {"max_hours": 40, "penalty": -50.0},
                },
                {
                    "id": 2,
                    "category": "mutual_exclusion",
                    "type": "HARD",
                    "enabled": True,
                    "params": {
                        "worker_a_id": "W001",
                        "worker_b_id": "W002",
                        "strictness": "HARD",
                        "penalty": -100.0,
                    },
                },
            ],
        )
    )
    db_session.commit()

    registry = _build_constraint_registry(db_session, test_session_id)
    assert any(isinstance(c, MutualExclusionConstraint) for c in registry._constraints)
    assert len(registry._constraints) > 3
