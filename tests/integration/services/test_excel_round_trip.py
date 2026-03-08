"""Round-trip integration test for forgiving-parser-compatible Excel export/import."""

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
    constraints_df: pd.DataFrame,
) -> bytes:
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
        constraints_df.to_excel(writer, sheet_name="Constraints", index=False)
    out.seek(0)
    return out.read()


def test_full_state_export_reimports_without_warnings(
    db_session, test_session_id, session_id_factory
):
    source_excel = _build_excel(
        workers_df=pd.DataFrame(
            [
                {
                    "Worker ID": "W001",
                    "Name": "Alice",
                    "Skills": "Chef:4,Waiter:3",
                    "Monday": "08:00-16:00",
                },
                {
                    "Worker ID": "W002",
                    "Name": "Bob",
                    "Skills": "Cook:4,Dishwasher:3",
                    "Monday": "12:00-20:00",
                },
            ]
        ),
        shifts_df=pd.DataFrame(
            [
                {
                    "Day": "Monday",
                    "Shift Name": "Lunch",
                    "Start Time": "08:00",
                    "End Time": "16:00",
                    "Tasks": "#1: [Chef:4] x 1 #2: [Cook:4] x 1",
                }
            ]
        ),
        constraints_df=pd.DataFrame(
            [
                {
                    "Type": "Mutual Exclusion",
                    "Subject": "W001",
                    "Target": "W002",
                    "Strictness": "HARD",
                }
            ]
        ),
    )

    source_service = ExcelService(db_session, test_session_id)
    first_import = source_service.import_excel(source_excel)
    assert not first_import.get("warnings")

    exported_buffer = source_service.export_full_state()
    exported_bytes = exported_buffer.getvalue()
    assert exported_bytes

    round_trip_session_id = session_id_factory("round-trip")
    round_trip_service = ExcelService(db_session, round_trip_session_id)
    second_import = round_trip_service.import_excel(exported_bytes)

    assert second_import["workers"] == first_import["workers"]
    assert second_import["shifts"] == first_import["shifts"]
    assert not second_import.get("warnings")

    config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=round_trip_session_id)
        .first()
    )
    assert config is not None
    for constraint in config.constraints or []:
        assert str(constraint.get("type", "")).upper() in {"HARD", "SOFT"}
