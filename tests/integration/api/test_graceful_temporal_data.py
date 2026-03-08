"""Integration tests for graceful worker availability warnings and strict shift enforcement.

Phase 5 tests per the Architectural Master Plan:
- TestWorkerMissingAvailabilityWarning: Workers with missing/empty availability
  must be saved (201) and the response must include a non-empty `warnings` field.
- TestStrictShiftEnforcement: Shifts with missing or null times must be rejected
  at every layer (422 at API, ValueError at repo).
"""

import uuid

import pytest
from datetime import datetime

from repositories.sql_shift_repo import SQLShiftRepository

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_session_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Worker Availability Warnings
# ---------------------------------------------------------------------------

class TestWorkerMissingAvailabilityWarning:
    """Workers with empty or absent availability must be accepted (201) with a warning."""

    def test_worker_without_availability_key_returns_201_with_warning(
        self, client, id_factory
    ):
        """POST a worker with no 'availability' key — must be saved and warn."""
        session_id = _valid_session_id()
        payload = {
            "worker_id": id_factory("worker"),
            "name": "No Avail Worker",
            "attributes": {"skills": {"Chef": 3}, "wage": 20.0},
        }
        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warnings" in body, "Response must include a 'warnings' field"
        assert len(body["warnings"]) > 0, "warnings must be non-empty for worker with no availability"
        warning_text = " ".join(body["warnings"]).lower()
        assert "availability" in warning_text, (
            f"Warning should mention 'availability', got: {body['warnings']}"
        )

    def test_worker_with_empty_availability_dict_returns_201_with_warning(
        self, client, id_factory
    ):
        """POST a worker with an empty availability dict — must be saved and warn."""
        session_id = _valid_session_id()
        payload = {
            "worker_id": id_factory("worker"),
            "name": "Empty Avail Worker",
            "attributes": {"skills": {}, "availability": {}},
        }
        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warnings" in body
        assert len(body["warnings"]) > 0, (
            "Worker with empty availability dict should have a warning"
        )

    def test_worker_with_full_availability_has_empty_warnings(
        self, client, id_factory
    ):
        """POST a worker with MON-FRI availability — warnings must be empty."""
        session_id = _valid_session_id()
        payload = {
            "worker_id": id_factory("worker"),
            "name": "Full Avail Worker",
            "attributes": {
                "skills": {"Waiter": 3},
                "availability": {
                    "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"},
                    "TUE": {"timeRange": "08:00-16:00", "preference": "NEUTRAL"},
                    "WED": {"timeRange": "09:00-17:00", "preference": "NEUTRAL"},
                    "THU": {"timeRange": "09:00-17:00", "preference": "NEUTRAL"},
                    "FRI": {"timeRange": "08:00-16:00", "preference": "LOW"},
                },
            },
        }
        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "warnings" in body
        assert body["warnings"] == [], (
            f"Worker with full availability must have no warnings, got: {body['warnings']}"
        )

    def test_get_all_workers_response_includes_warnings_field(
        self, client, id_factory
    ):
        """GET /workers — every worker in the list must have a 'warnings' key."""
        session_id = _valid_session_id()
        # Create one worker with availability and one without
        for i in range(2):
            avail = (
                {"MON": {"timeRange": "08:00-16:00", "preference": "NEUTRAL"}}
                if i == 0
                else {}
            )
            client.post(
                "/api/v1/workers",
                json={
                    "worker_id": id_factory("worker"),
                    "name": f"Worker {i}",
                    "attributes": {"skills": {}, "availability": avail},
                },
                cookies={"session_id": session_id},
            )

        resp = client.get("/api/v1/workers", cookies={"session_id": session_id})
        assert resp.status_code == 200, resp.text
        workers = resp.json()
        assert len(workers) == 2
        for w in workers:
            assert "warnings" in w, (
                f"GET /workers item missing 'warnings' key: {list(w.keys())}"
            )

    def test_put_worker_response_includes_warnings_field(
        self, client, id_factory
    ):
        """PUT /workers/{id} — response must include 'warnings' key.

        The PUT endpoint also returns WorkerRead, so it must also carry warnings.
        """
        session_id = _valid_session_id()
        worker_id = id_factory("worker")
        # Create the worker first
        client.post(
            "/api/v1/workers",
            json={
                "worker_id": worker_id,
                "name": "Update Target Worker",
                "attributes": {},
            },
            cookies={"session_id": session_id},
        )

        # Update with no availability — should trigger warning
        resp = client.put(
            f"/api/v1/workers/{worker_id}",
            json={
                "worker_id": worker_id,
                "name": "Update Target Worker",
                "attributes": {},
            },
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "warnings" in body, (
            f"PUT /workers/{{id}} response missing 'warnings' field: {list(body.keys())}"
        )
        assert len(body["warnings"]) > 0, (
            "Worker updated with no availability must have a warning"
        )


# ---------------------------------------------------------------------------
# Strict Shift Enforcement
# ---------------------------------------------------------------------------

class TestStrictShiftEnforcement:
    """Shifts with missing or null times must be rejected at every layer."""

    def test_create_shift_without_start_time_returns_422(
        self, client, id_factory
    ):
        """POST shift missing start_time — must return 422."""
        session_id = _valid_session_id()
        payload = {
            "shift_id": id_factory("shift"),
            "name": "Night",
            "end_time": "2024-01-01T20:00:00",
        }
        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_create_shift_without_end_time_returns_422(
        self, client, id_factory
    ):
        """POST shift missing end_time — must return 422."""
        session_id = _valid_session_id()
        payload = {
            "shift_id": id_factory("shift"),
            "name": "Night",
            "start_time": "2024-01-01T08:00:00",
        }
        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_create_shift_with_both_times_missing_returns_422(
        self, client, id_factory
    ):
        """POST shift with no time fields at all — must return 422."""
        session_id = _valid_session_id()
        payload = {
            "shift_id": id_factory("shift"),
            "name": "Night",
        }
        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_create_shift_with_null_start_time_returns_422(
        self, client, id_factory
    ):
        """POST shift with start_time: null — must return 422."""
        session_id = _valid_session_id()
        payload = {
            "shift_id": id_factory("shift"),
            "name": "Night",
            "start_time": None,
            "end_time": "2024-01-01T20:00:00",
        }
        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_create_shift_with_null_end_time_returns_422(
        self, client, id_factory
    ):
        """POST shift with end_time: null — must return 422."""
        session_id = _valid_session_id()
        payload = {
            "shift_id": id_factory("shift"),
            "name": "Night",
            "start_time": "2024-01-01T08:00:00",
            "end_time": None,
        }
        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies={"session_id": session_id},
        )
        assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    def test_shift_repo_create_from_schema_raises_on_none_start_time(
        self, db_session, test_session_id, id_factory
    ):
        """Direct unit test: create_from_schema with start_time=None raises ValueError.

        Confirms the datetime.now() fallback has been removed.
        """
        repo = SQLShiftRepository(db_session, test_session_id)
        with pytest.raises(ValueError, match="start_time"):
            repo.create_from_schema(
                {
                    "shift_id": id_factory("shift"),
                    "name": "Bad Shift",
                    "start_time": None,
                    "end_time": datetime(2024, 1, 1, 20, 0),
                }
            )

    def test_shift_repo_create_from_schema_raises_on_none_end_time(
        self, db_session, test_session_id, id_factory
    ):
        """Direct unit test: create_from_schema with end_time=None raises ValueError.

        Confirms the datetime.now() fallback has been removed.
        """
        repo = SQLShiftRepository(db_session, test_session_id)
        with pytest.raises(ValueError, match="end_time"):
            repo.create_from_schema(
                {
                    "shift_id": id_factory("shift"),
                    "name": "Bad Shift",
                    "start_time": datetime(2024, 1, 1, 8, 0),
                    "end_time": None,
                }
            )

    def test_shift_repo_to_domain_raises_on_corrupt_db_times(
        self, db_session, test_session_id
    ):
        """Direct unit test: _to_domain() raises ValueError on corrupt DB times.

        Confirms the TimeWindow(datetime.now(), datetime.now()) fallback is gone.
        """
        from data.models import ShiftModel

        corrupt_model = ShiftModel(
            shift_id="CORRUPT_001",
            name="Corrupt Shift",
            start_time=None,
            end_time=None,
            session_id=test_session_id,
        )
        repo = SQLShiftRepository(db_session, test_session_id)
        with pytest.raises(ValueError, match="corrupt time data"):
            repo._to_domain(corrupt_model)
