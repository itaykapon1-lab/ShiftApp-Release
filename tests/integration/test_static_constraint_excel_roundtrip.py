"""Integration tests for static constraint strictness Excel round-tripping."""

from io import BytesIO

import pandas as pd
import pytest

from data.models import SessionConfigModel
from services.excel_service import ExcelService
from solver.constraints.base import ConstraintType


pytestmark = [pytest.mark.integration]


def _build_legacy_static_constraints_workbook(*, include_strictness_column: bool) -> bytes:
    workers_df = pd.DataFrame(
        [
            {
                "Worker ID": "W001",
                "Name": "Alice",
                "Wage": 20,
                "Min Hours": 0,
                "Max Hours": 40,
                "Skills": "Cook:5",
                "Monday": "08:00-16:00",
            }
        ]
    )
    shifts_df = pd.DataFrame(
        [
            {
                "Day": "Monday",
                "Shift Name": "Morning",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Tasks": "[Cook:3] x 1",
            }
        ]
    )

    rows = [
        {
            "Type": "Max Hours",
            "Subject": "",
            "Target": "",
            "Value": 32,
            "Strictness": "",
            "Penalty": -50,
        },
        {
            "Type": "Avoid Consecutive Shifts",
            "Subject": "",
            "Target": "",
            "Value": 11,
            "Strictness": "",
            "Penalty": -30,
        },
    ]
    constraints_df = pd.DataFrame(rows)
    if not include_strictness_column:
        constraints_df = constraints_df.drop(columns=["Strictness"])

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
        constraints_df.to_excel(writer, sheet_name="Constraints", index=False)
    output.seek(0)
    return output.read()


def _constraint_by_category(constraints: list[dict], category: str) -> dict:
    constraint = next((c for c in constraints if c.get("category") == category), None)
    assert constraint is not None, f"Missing category '{category}' in constraints: {constraints}"
    return constraint


def test_static_max_hours_hard_strictness_round_trip_via_excel(
    db_session, session_id_factory, test_session_id
):
    db_session.add(
        SessionConfigModel(
            session_id=test_session_id,
            constraints=[
                {
                    "id": 1,
                    "category": "max_hours_per_week",
                    "type": "HARD",
                    "enabled": True,
                    "params": {
                        "max_hours": 32,
                        "penalty": -50.0,
                        "strictness": "HARD",
                    },
                }
            ],
        )
    )
    db_session.commit()

    exported = ExcelService(db_session, test_session_id).export_full_state().read()

    imported_session_id = session_id_factory()
    ExcelService(db_session, imported_session_id).import_excel(exported)

    imported_config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=imported_session_id)
        .first()
    )
    assert imported_config is not None

    max_hours = _constraint_by_category(imported_config.constraints, "max_hours_per_week")
    assert str(max_hours.get("type", "")).upper() == "HARD"
    assert str(max_hours.get("params", {}).get("strictness", "")).upper() == "HARD"


@pytest.mark.parametrize(
    "include_strictness_column",
    [True, False],
    ids=["empty_strictness_cell", "missing_strictness_column"],
)
def test_legacy_static_constraints_default_to_soft_when_strictness_is_empty_or_missing(
    db_session, test_session_id, include_strictness_column
):
    legacy_workbook = _build_legacy_static_constraints_workbook(
        include_strictness_column=include_strictness_column
    )

    ExcelService(db_session, test_session_id).import_excel(legacy_workbook)

    config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=test_session_id)
        .first()
    )
    assert config is not None

    for category in ("max_hours_per_week", "avoid_consecutive_shifts"):
        constraint = _constraint_by_category(config.constraints, category)
        assert str(constraint.get("type", "")).upper() == ConstraintType.SOFT.name
        assert (
            str(constraint.get("params", {}).get("strictness", "")).upper()
            == ConstraintType.SOFT.name
        )
