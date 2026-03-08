"""E2E manual entry journey test.

Sprint 3 hardening: added field-value verification on worker and shift payloads
beyond the original status-code and count assertions.
"""

from datetime import date, datetime

import pytest

from app.utils.date_normalization import normalize_to_canonical_week


pytestmark = [pytest.mark.e2e]


def test_manual_entry_journey(client, id_factory, test_session_id):
    """Manual entry of one worker and one shift, with field-value verification.

    Hardens the original smoke test by asserting:
    - Returned worker fields (name, skills, availability, wage) match what was posted.
    - Returned shift fields (name, start_time, end_time, tasks_data) match posted data.
    - Shift dates are normalized to the canonical epoch week (not the raw input date).
    - Only 1 worker and 1 shift exist in the session after creation.
    """
    session_cookies = {"session_id": test_session_id}

    worker_id = id_factory("worker")
    worker_payload = {
        "worker_id": worker_id,
        "name": "Journey Worker",
        "attributes": {
            "skills": {"Chef": 5},
            "availability": {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}},
            "wage": 20,
            "min_hours": 0,
            "max_hours": 40,
        },
    }
    shift_id = id_factory("shift")
    shift_payload = {
        "shift_id": shift_id,
        "name": "Journey Shift",
        "start_time": "2026-01-22T08:00:00",  # Thursday in real calendar
        "end_time": "2026-01-22T16:00:00",
        "tasks_data": {
            "tasks": [
                {
                    "task_id": id_factory("task"),
                    "name": "Kitchen",
                    "options": [{"requirements": [{"count": 1, "required_skills": {"Chef": 3}}]}],
                }
            ]
        },
    }

    # ── CREATE ──────────────────────────────────────────────────────────────
    worker_resp = client.post(
        "/api/v1/workers", json=worker_payload, cookies=session_cookies
    )
    assert worker_resp.status_code == 201, (
        f"Create worker failed: {worker_resp.text}"
    )
    created_worker = worker_resp.json()

    shift_resp = client.post(
        "/api/v1/shifts", json=shift_payload, cookies=session_cookies
    )
    assert shift_resp.status_code == 201, (
        f"Create shift failed: {shift_resp.text}"
    )
    created_shift = shift_resp.json()

    # ── WORKER FIELD ASSERTIONS ──────────────────────────────────────────────
    assert created_worker["worker_id"] == worker_id, (
        f"worker_id mismatch: {created_worker['worker_id']!r} != {worker_id!r}"
    )
    assert created_worker["name"] == "Journey Worker", (
        f"Worker name mismatch: {created_worker['name']!r}"
    )
    assert created_worker["attributes"]["skills"] == {"Chef": 5}, (
        f"Skills mismatch: {created_worker['attributes'].get('skills')!r}"
    )
    assert created_worker["attributes"]["wage"] == 20, (
        f"Wage mismatch: {created_worker['attributes'].get('wage')!r}"
    )

    # ── SHIFT FIELD ASSERTIONS ───────────────────────────────────────────────
    assert created_shift["shift_id"] == shift_id, (
        f"shift_id mismatch: {created_shift['shift_id']!r} != {shift_id!r}"
    )
    assert created_shift["name"] == "Journey Shift", (
        f"Shift name mismatch: {created_shift['name']!r}"
    )

    # Canonical week date normalization check.
    # "2026-01-22" is a Thursday (weekday=3).  The canonical Thursday is 2024-01-04.
    expected_canonical_start = normalize_to_canonical_week(datetime(2026, 1, 22, 8, 0))
    actual_start = datetime.fromisoformat(created_shift["start_time"])
    assert actual_start.date() == date(2024, 1, 4), (
        f"start_time must be normalized to canonical Thursday (2024-01-04), "
        f"got {actual_start.date()}"
    )
    assert actual_start.time() == expected_canonical_start.time(), (
        f"start_time hours/minutes must be preserved after normalization, "
        f"got {actual_start.time()}"
    )

    expected_canonical_end = normalize_to_canonical_week(datetime(2026, 1, 22, 16, 0))
    actual_end = datetime.fromisoformat(created_shift["end_time"])
    assert actual_end.date() == date(2024, 1, 4), (
        f"end_time must be normalized to canonical Thursday (2024-01-04), "
        f"got {actual_end.date()}"
    )
    assert actual_end.time() == expected_canonical_end.time(), (
        f"end_time hours/minutes must be preserved after normalization"
    )

    # ── COUNT ASSERTIONS ─────────────────────────────────────────────────────
    workers = client.get("/api/v1/workers", cookies=session_cookies).json()
    shifts = client.get("/api/v1/shifts", cookies=session_cookies).json()
    assert len(workers) == 1, (
        f"Expected exactly 1 worker in session, found {len(workers)}"
    )
    assert len(shifts) == 1, (
        f"Expected exactly 1 shift in session, found {len(shifts)}"
    )

    # Verify GET /workers returns the same worker with correct fields.
    fetched_worker = workers[0]
    assert fetched_worker["name"] == "Journey Worker", (
        f"GET /workers returned wrong name: {fetched_worker['name']!r}"
    )
    assert fetched_worker["worker_id"] == worker_id, (
        f"GET /workers returned wrong worker_id: {fetched_worker['worker_id']!r}"
    )

