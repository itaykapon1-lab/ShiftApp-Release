"""Integration tests for forgiving Excel parser auto-corrections."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from data.models import SessionConfigModel
from services.excel_service import ExcelService


pytestmark = [pytest.mark.integration]


def _build_excel(
    workers_df: pd.DataFrame,
    shifts_df: pd.DataFrame,
    constraints_df: pd.DataFrame | None = None,
) -> bytes:
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
        if constraints_df is not None:
            constraints_df.to_excel(writer, sheet_name="Constraints", index=False)
    out.seek(0)
    return out.read()


def _assert_warning_contains(warnings: list[str], expected_message: str) -> None:
    assert any(expected_message in warning for warning in warnings), (
        f"Expected warning message not found.\n"
        f"Expected: {expected_message}\n"
        f"Actual warnings: {warnings}"
    )


def test_unknown_strictness_defaults_to_hard_and_warns(db_session, test_session_id):
    content = _build_excel(
        workers_df=pd.DataFrame(
            [
                {"Worker ID": "W001", "Name": "Alice", "Monday": "08:00-16:00"},
                {"Worker ID": "W002", "Name": "Bob", "Monday": "08:00-16:00"},
            ]
        ),
        shifts_df=pd.DataFrame(
            [
                {
                    "Day": "Monday",
                    "Shift Name": "Morning",
                    "Start Time": "08:00",
                    "End Time": "16:00",
                    "Tasks": "[Chef:3] x 1",
                }
            ]
        ),
        constraints_df=pd.DataFrame(
            [
                {
                    "Type": "Mutual Exclusion",
                    "Subject": "W001",
                    "Target": "W002",
                    "Strictness": "MAYBE",
                }
            ]
        ),
    )

    service = ExcelService(db_session, test_session_id)
    result = service.import_excel(content)

    warnings = result.get("warnings", [])
    _assert_warning_contains(
        warnings,
        "Unknown strictness 'MAYBE' on row 2. Auto-defaulted to 'HARD'.",
    )

    db_session.expire_all()
    config = db_session.query(SessionConfigModel).filter_by(session_id=test_session_id).first()
    assert config is not None
    mutual = next(c for c in config.constraints if c.get("category") == "mutual_exclusion")
    assert mutual["type"] == "HARD"
    assert mutual["params"]["strictness"] == "HARD"
