"""Regression coverage for worker-preference and task-option-priority scoring pipeline."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from data.models import SessionConfigModel
from repositories.sql_repo import SQLShiftRepository, SQLWorkerRepository
from services.excel_service import ExcelService
from services.session_adapter import SessionDataManagerAdapter
from services.solver_service import _build_constraint_registry
from solver.solver_engine import ShiftSolver


pytestmark = [pytest.mark.integration]


def _build_priority_preference_workbook() -> bytes:
    workers_df = pd.DataFrame(
        [
            {
                "Worker ID": "W001",
                "Name": "Alice",
                "Wage": 20,
                "Min Hours": 0,
                "Max Hours": 40,
                "Skills": "Cook:5",
                "Monday": "08:00-16:00*",
            }
        ]
    )

    shifts_df = pd.DataFrame(
        [
            {
                "Day": "Monday",
                "Shift Name": "Priority Shift",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Tasks": "#1: [Chef:5] x 1 #2: [Cook:5] x 1",
            }
        ]
    )

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
    out.seek(0)
    return out.read()


def test_solver_reports_preference_bonus_and_priority_penalty_together(
    db_session,
    test_session_id,
):
    workbook = _build_priority_preference_workbook()
    ExcelService(db_session, test_session_id).import_excel(workbook)

    config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=test_session_id)
        .first()
    )
    assert config is not None
    categories = {c.get("category") for c in (config.constraints or [])}
    assert "worker_preferences" in categories
    assert "task_option_priority" in categories

    worker_repo = SQLWorkerRepository(db_session, session_id=test_session_id)
    shift_repo = SQLShiftRepository(db_session, session_id=test_session_id)
    workers = worker_repo.get_all()
    shifts = shift_repo.get_all()

    registry = _build_constraint_registry(db_session, test_session_id)
    constraint_names = {constraint.name for constraint in registry._constraints}
    assert "worker_preferences" in constraint_names
    assert "task_option_priority" in constraint_names

    solver = ShiftSolver(
        SessionDataManagerAdapter(workers=workers, shifts=shifts),
        constraint_registry=registry,
    )
    result = solver.solve()

    assert result["status"] in {"Optimal", "Feasible"}
    assert result["objective_value"] == pytest.approx(-10.0)

    assert "task_option_priority" in result["penalty_breakdown"]
    priority_breakdown = result["penalty_breakdown"]["task_option_priority"]
    assert priority_breakdown["violation_count"] == 1
    assert priority_breakdown["total_penalty"] == pytest.approx(-20.0)

    assert "task_option_priority" in result["violations"]
    priority_violations = result["violations"]["task_option_priority"]
    assert len(priority_violations) == 1
    assert priority_violations[0].penalty == pytest.approx(-20.0)
    assert priority_violations[0].observed_value == pytest.approx(2.0)

    assert len(result["assignments"]) == 1
    assignment = result["assignments"][0]
    assert assignment["worker_name"] == "Alice"
    assert assignment["score"] == pytest.approx(10.0)
    assert "+10 (Pref)" in assignment["score_breakdown"]
