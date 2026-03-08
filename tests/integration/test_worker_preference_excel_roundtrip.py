"""Integration tests for worker preference reward/penalty Excel persistence."""

from io import BytesIO

import pandas as pd
import pytest

from data.models import SessionConfigModel
from services.excel_service import ExcelService


pytestmark = [pytest.mark.integration]


def _build_legacy_worker_preferences_workbook() -> bytes:
    """Build an old-format workbook where worker_preferences has no Subject/Penalty."""
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

    # Legacy row: no Subject value and no Penalty value.
    constraints_df = pd.DataFrame(
        [
            {
                "Type": "Worker Preferences",
                "Subject": "",
                "Target": "",
                "Value": "True",
                "Strictness": "SOFT",
                "Penalty": "",
            }
        ]
    )

    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
        constraints_df.to_excel(writer, sheet_name="Constraints", index=False)
    out.seek(0)
    return out.read()


def _get_worker_preferences_constraint(constraints: list[dict]) -> dict:
    constraint = next((c for c in constraints if c.get("category") == "worker_preferences"), None)
    assert constraint is not None, f"worker_preferences not found in constraints: {constraints}"
    return constraint


def test_worker_preferences_custom_weights_round_trip_through_excel(
    db_session, session_id_factory, test_session_id
):
    constraints = [
        {
            "id": 1,
            "category": "worker_preferences",
            "type": "SOFT",
            "enabled": True,
            "params": {
                "enabled": True,
                "preference_reward": 25,
                "preference_penalty": -50,
            },
        }
    ]
    db_session.add(SessionConfigModel(session_id=test_session_id, constraints=constraints))
    db_session.commit()

    exported_bytes = ExcelService(db_session, test_session_id).export_full_state().read()

    imported_session_id = session_id_factory()
    ExcelService(db_session, imported_session_id).import_excel(exported_bytes)

    imported_config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=imported_session_id)
        .first()
    )
    assert imported_config is not None, "Imported session must have a SessionConfigModel"

    worker_preferences = _get_worker_preferences_constraint(imported_config.constraints)
    params = worker_preferences.get("params", {})

    assert params.get("preference_reward") == pytest.approx(25)
    assert params.get("preference_penalty") == pytest.approx(-50)


def test_worker_preferences_legacy_excel_falls_back_to_default_weights(
    db_session, test_session_id
):
    legacy_workbook = _build_legacy_worker_preferences_workbook()

    result = ExcelService(db_session, test_session_id).import_excel(legacy_workbook)

    config = (
        db_session.query(SessionConfigModel)
        .filter_by(session_id=test_session_id)
        .first()
    )
    assert config is not None, "Session config should be created during import"

    worker_preferences = _get_worker_preferences_constraint(config.constraints)
    params = worker_preferences.get("params", {})

    assert params.get("preference_reward") == pytest.approx(10)
    assert params.get("preference_penalty") == pytest.approx(-100)

    warnings = result.get("warnings", [])
    assert any("Worker Preferences reward" in w and "defaulting to 10" in w for w in warnings)
    assert any("Worker Preferences penalty" in w and "defaulting to -100" in w for w in warnings)
