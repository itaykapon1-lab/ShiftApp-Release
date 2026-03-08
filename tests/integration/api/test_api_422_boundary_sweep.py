"""API input validation boundary sweep — 422 contract tests.

PILLAR 1 of the Backend Testing Roadmap.

Covers edge cases at the API boundary for:
- POST /api/v1/workers  (scenarios A1–A3, invalid availability/day)
- POST /api/v1/shifts   (malformed datetime/end_time)
- PUT  /api/v1/constraints (scenario A6)

Each test class maps to one endpoint family.  Within each class tests are
ordered from most common input to most exotic.
"""

import uuid

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.contract]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker_id() -> str:
    """Return a unique worker ID."""
    return f"w_{uuid.uuid4().hex[:8]}"


def _make_shift_id() -> str:
    """Return a unique shift ID."""
    return f"s_{uuid.uuid4().hex[:8]}"


def _valid_worker_payload(worker_id: str | None = None) -> dict:
    """Return a valid WorkerCreate payload for use as a base."""
    return {
        "worker_id": worker_id or _make_worker_id(),
        "name": "Boundary Test Worker",
        "attributes": {
            "skills": {"Chef": 5},
            "availability": {
                "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"},
            },
            "wage": 20.0,
            "min_hours": 0,
            "max_hours": 40,
        },
    }


def _valid_shift_payload(shift_id: str | None = None) -> dict:
    """Return a valid ShiftCreate payload for use as a base."""
    return {
        "shift_id": shift_id or _make_shift_id(),
        "name": "Boundary Test Shift",
        "start_time": "2024-01-01T08:00:00",
        "end_time": "2024-01-01T16:00:00",
        "tasks_data": {"tasks": []},
    }


def _session_cookies(session_id: str) -> dict:
    """Return session cookie dict."""
    return {"session_id": session_id}


# ---------------------------------------------------------------------------
# Worker validation (A1–A3, invalid availability, invalid day)
# ---------------------------------------------------------------------------


class TestWorkerValidation422:
    """POST /api/v1/workers must reject invalid inputs with HTTP 422."""

    def test_a1_whitespace_only_name_is_rejected(self, client, test_session_id):
        """A1: A name that is only whitespace must not be stored (422).

        The model_validator in WorkerCreate strips whitespace and raises
        ValueError("Worker name cannot be empty."), which Pydantic converts
        to a 422 response.
        """
        payload = _valid_worker_payload()
        payload["name"] = "   "  # only spaces

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for whitespace-only name, got {resp.status_code}: {resp.text}"
        )
        errors = resp.json()["detail"]
        # Pydantic surfaces validation errors as a list; at least one must
        # mention 'name' or 'cannot be empty'.
        error_text = str(errors).lower()
        assert "name" in error_text or "empty" in error_text, (
            f"Expected 'name'/'empty' in error detail, got: {errors}"
        )

    def test_a2_min_hours_exceeds_max_hours_is_rejected(self, client, test_session_id):
        """A2: min_hours > max_hours must be rejected with 422.

        The model_validator raises ValueError when min_hours(30) > max_hours(20).
        """
        payload = _valid_worker_payload()
        payload["attributes"]["min_hours"] = 30
        payload["attributes"]["max_hours"] = 20

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for min_hours > max_hours, got {resp.status_code}: {resp.text}"
        )
        error_text = str(resp.json()["detail"]).lower()
        assert "min_hours" in error_text or "max_hours" in error_text or "exceed" in error_text, (
            f"Expected hours-range error in detail, got: {resp.json()['detail']}"
        )

    def test_a3_negative_wage_is_rejected(self, client, test_session_id):
        """A3: A negative wage must be rejected with 422.

        The model_validator raises ValueError("Wage cannot be negative: -50").
        """
        payload = _valid_worker_payload()
        payload["attributes"]["wage"] = -50

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for negative wage, got {resp.status_code}: {resp.text}"
        )
        error_text = str(resp.json()["detail"]).lower()
        assert "wage" in error_text or "negative" in error_text, (
            f"Expected 'wage'/'negative' in error detail, got: {resp.json()['detail']}"
        )

    def test_invalid_availability_format_is_rejected(self, client, test_session_id):
        """Availability time range with wrong format must be rejected with 422.

        Providing 'anytime' (an invalid placeholder value) should be caught by
        validate_availability_dict and raise ValueError.
        """
        payload = _valid_worker_payload()
        payload["attributes"]["availability"] = {
            "MON": "anytime",  # invalid placeholder
        }

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for invalid availability 'anytime', "
            f"got {resp.status_code}: {resp.text}"
        )

    def test_invalid_day_code_in_availability_is_rejected(self, client, test_session_id):
        """Availability with an invalid day code must be rejected with 422.

        'FUNDAY' is not in VALID_DAYS and should trigger an error.
        """
        payload = _valid_worker_payload()
        payload["attributes"]["availability"] = {
            "FUNDAY": "08:00-16:00",  # not a real day
        }

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for invalid day code 'FUNDAY', "
            f"got {resp.status_code}: {resp.text}"
        )
        error_text = str(resp.json()["detail"]).lower()
        assert "funday" in error_text or "day" in error_text or "invalid" in error_text, (
            f"Expected day-code error in detail, got: {resp.json()['detail']}"
        )

    def test_negative_min_hours_is_rejected(self, client, test_session_id):
        """Negative min_hours must be rejected with 422."""
        payload = _valid_worker_payload()
        payload["attributes"]["min_hours"] = -5

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for negative min_hours, got {resp.status_code}: {resp.text}"
        )

    def test_zero_length_time_range_in_availability_is_rejected(self, client, test_session_id):
        """Time range where start == end (0-length shift) must be rejected."""
        payload = _valid_worker_payload()
        payload["attributes"]["availability"] = {
            "MON": "08:00-08:00",  # zero-length range
        }

        resp = client.post(
            "/api/v1/workers",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for zero-length time range '08:00-08:00', "
            f"got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# Shift validation
# ---------------------------------------------------------------------------


class TestShiftValidation422:
    """POST /api/v1/shifts must reject invalid inputs with HTTP 422."""

    def test_malformed_end_time_returns_error(self, client, test_session_id):
        """A non-parseable end_time string must not silently succeed."""
        payload = _valid_shift_payload()
        payload["end_time"] = "not-a-date"

        resp = client.post(
            "/api/v1/shifts",
            json=payload,
            cookies=_session_cookies(test_session_id),
        )

        # Must not be 201 — some form of error is required.
        assert resp.status_code != 201, (
            f"Server accepted a malformed end_time 'not-a-date' with 201 — "
            f"this is a data corruption risk."
        )
        # Acceptable outcomes: 422 (validation) or 500 (non-ideal, but safe).
        assert resp.status_code in (422, 500), (
            f"Unexpected status code {resp.status_code} for malformed end_time"
        )


# ---------------------------------------------------------------------------
# Constraint validation (A6)
# ---------------------------------------------------------------------------


class TestConstraintValidation422:
    """PUT /api/v1/constraints must reject invalid constraint configurations.

    NOTE: The constraint validation route (_validate_schema_driven_constraints)
    uses constraint_definitions.get(category) which requires register_core_constraints()
    to have been called.  The minimal test FastAPI app does NOT call the startup
    lifespan, so the registry must be initialized manually in each test.
    """

    def test_a6_max_hours_per_week_negative_value_is_rejected(
        self, client, test_session_id
    ):
        """A6: max_hours_per_week with value -5 must be rejected with 422.

        MaxHoursPerWeekConfig has `ge=0` on its max_hours field.
        _validate_schema_driven_constraints() calls model_validate() and raises
        HTTPException(422) when validation fails.

        Requires the constraint registry to be initialized first — the test
        app does not call the startup lifespan.
        """
        # Ensure the constraint registry is initialized before the route can
        # validate "max_hours_per_week" against its Pydantic config model.
        from solver.constraints.definitions import register_core_constraints
        try:
            register_core_constraints()
        except ValueError:
            pass  # Already registered in this process — idempotent.

        constraints_payload = {
            "constraints": [
                {
                    "category": "max_hours_per_week",
                    "params": {"max_hours": -5},
                    "enabled": True,
                    "type": "HARD",
                }
            ]
        }

        resp = client.put(
            "/api/v1/constraints",
            json=constraints_payload,
            cookies=_session_cookies(test_session_id),
        )

        assert resp.status_code == 422, (
            f"Expected 422 for max_hours=-5 (violates ge=0), "
            f"got {resp.status_code}: {resp.text}"
        )
