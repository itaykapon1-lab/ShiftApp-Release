"""API contract tests for shift routes."""

from datetime import datetime

import pytest

from app.utils.date_normalization import normalize_to_canonical_week


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_shift_create_update_delete_contract_and_canonical_dates(client, id_factory, test_session_id):
    shift_id = id_factory("shift")
    payload = {
        "shift_id": shift_id,
        "name": "Contract Shift",
        "start_time": "2026-01-22T10:00:00",
        "end_time": "2026-01-22T18:00:00",
        "tasks_data": {"tasks": []},
    }

    create = client.post("/api/v1/shifts", json=payload, cookies={"session_id": test_session_id})
    assert create.status_code == 201
    created = create.json()
    assert datetime.fromisoformat(created["start_time"]) == normalize_to_canonical_week(datetime(2026, 1, 22, 10, 0))

    payload["name"] = "Contract Shift Updated"
    update = client.put(f"/api/v1/shifts/{shift_id}", json=payload, cookies={"session_id": test_session_id})
    assert update.status_code == 200
    assert update.json()["name"] == "Contract Shift Updated"

    delete = client.delete(f"/api/v1/shifts/{shift_id}", cookies={"session_id": test_session_id})
    assert delete.status_code == 200

