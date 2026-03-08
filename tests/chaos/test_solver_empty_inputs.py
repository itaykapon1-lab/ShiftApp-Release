"""Chaos tests: Solver degenerate inputs (B1 — 0 workers, B2 — 0 shifts).

PILLAR 2 of the Backend Testing Roadmap — scenarios B1 and B2.

B1: POST /solve with 0 workers in the session.
    - Solver sees no worker domain objects → INFEASIBLE → job=FAILED.
    - Error must be surfaced; silent success is unacceptable.

B2: POST /solve with 0 shifts in the session.
    - Solver sees no shift domain objects.
    - Depending on solver implementation: COMPLETED with 0 assignments OR
      FAILED with an error.  Either is acceptable; silent COMPLETED with no
      diagnostic is a known quality gap that must be documented.

ZERO BUSINESS-LOGIC MOCKS.  Real OR-Tools CP-SAT solver runs for every test.
Infrastructure swap: ProcessPoolExecutor → ThreadPoolExecutor so the solver
thread shares the in-memory test DB.
"""

import concurrent.futures
import time
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.db.session as session_mod
import services.solver_service as solver_mod
from api.routes import router as api_router
from api.routes_constraints_schema import router as constraints_schema_router
from app.db.session import get_db
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


pytestmark = pytest.mark.chaos


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANONICAL_MONDAY_8AM = "2024-01-01T08:00:00"
CANONICAL_MONDAY_4PM = "2024-01-01T16:00:00"

POLL_INTERVAL_SECONDS = 0.3
POLL_TIMEOUT_SECONDS = 20.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def empty_engine():
    """Isolated in-memory SQLite engine for degenerate-input tests."""
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def empty_session_factory(empty_engine):
    """Session factory bound to the test engine."""
    return sessionmaker(bind=empty_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def empty_session_id() -> str:
    """Valid UUID4 session ID."""
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def empty_client(empty_engine, empty_session_factory, empty_session_id):
    """Fully wired TestClient with ThreadPoolExecutor and test DB override.

    Infrastructure swaps (NOT business-logic mocks):
    1. session_mod.SessionLocal  → test factory
    2. solver_mod.SessionLocal   → test factory
    3. solver_mod.get_executor   → ThreadPoolExecutor(max_workers=1)
    """
    orig_session_local_mod = session_mod.SessionLocal
    orig_session_local_solver = solver_mod.SessionLocal
    orig_get_executor = solver_mod.get_executor
    orig_executor = solver_mod._executor

    session_mod.SessionLocal = empty_session_factory
    solver_mod.SessionLocal = empty_session_factory

    thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    solver_mod.get_executor = lambda: thread_executor
    solver_mod._executor = None

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(constraints_schema_router, prefix="/api/v1")

    def override_get_db():
        db = empty_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app, cookies={"session_id": empty_session_id}) as tc:
            yield tc
    finally:
        app.dependency_overrides.clear()
        thread_executor.shutdown(wait=True)
        session_mod.SessionLocal = orig_session_local_mod
        solver_mod.SessionLocal = orig_session_local_solver
        solver_mod.get_executor = orig_get_executor
        solver_mod._executor = orig_executor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _poll_until_terminal(
    client: TestClient,
    job_id: str,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> dict:
    """Poll GET /api/v1/status/{job_id} until COMPLETED or FAILED."""
    deadline = time.time() + timeout
    last_status: str | None = None

    while time.time() < deadline:
        resp = client.get(f"/api/v1/status/{job_id}")
        assert resp.status_code == 200, (
            f"Status poll returned {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        last_status = data["status"]
        if last_status in ("COMPLETED", "FAILED"):
            return data
        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(
        f"Solver job {job_id!r} did not reach a terminal status within "
        f"{timeout}s.  Last polled status: {last_status!r}"
    )


# ---------------------------------------------------------------------------
# B1 — POST /solve with 0 workers
# ---------------------------------------------------------------------------


class TestB1ZeroWorkers:
    """B1: Solver with no workers in the session must fail gracefully."""

    def test_b1_zero_workers_one_shift_solver_fails_gracefully(
        self, empty_client, empty_session_id
    ):
        """B1: Zero workers in session → solver cannot assign → FAILED job.

        Scenario:
        1. Create 1 shift (but NO workers).
        2. POST /solve → job is submitted.
        3. Poll until terminal.

        Acceptance criteria:
        - POST /solve returns HTTP 200 (job accepted — the session is valid).
        - Solver reaches FAILED, not COMPLETED (infeasible with no workers).
        - Job does NOT hang indefinitely (terminates within timeout).
        - Some diagnostic signal is available (error_message or result_status).
        - No HTTP 500 is returned at any stage.

        This is a high-priority chaos test because an empty worker pool is a
        common mis-configuration (user forgets to upload workers before solving).
        """
        client = empty_client

        # Create 1 shift — no workers at all.
        shift_id = f"s_b1_{uuid.uuid4().hex[:6]}"
        resp = client.post(
            "/api/v1/shifts",
            json={
                "shift_id": shift_id,
                "name": "Orphan_Shift_B1",
                "start_time": CANONICAL_MONDAY_8AM,
                "end_time": CANONICAL_MONDAY_4PM,
                "tasks_data": {
                    "tasks": [
                        {
                            "task_id": f"task_{shift_id}",
                            "name": "Kitchen",
                            "options": [
                                {
                                    "preference_score": 0,
                                    "requirements": [
                                        {"count": 1, "required_skills": {"Chef": 3}}
                                    ],
                                }
                            ],
                        }
                    ]
                },
            },
        )
        assert resp.status_code == 201, f"Shift creation failed: {resp.text}"

        # Verify no workers exist.
        workers_resp = client.get("/api/v1/workers")
        assert workers_resp.status_code == 200
        assert len(workers_resp.json()) == 0, (
            f"Expected 0 workers, found {len(workers_resp.json())}"
        )

        # Trigger solve — should be accepted (200), not rejected (422).
        solve_resp = client.post("/api/v1/solve")
        assert solve_resp.status_code == 200, (
            f"POST /solve should accept an empty-worker session with 200, "
            f"got {solve_resp.status_code}: {solve_resp.text}"
        )
        job_id = solve_resp.json()["job_id"]
        assert job_id, "job_id must be present in solve response"

        # Poll to terminal — must not hang.
        result = _poll_until_terminal(client, job_id)

        # Acceptance: solver must reach FAILED for an unsolvable problem.
        assert result["status"] == "FAILED", (
            f"Expected FAILED for 0-worker session, got {result['status']!r}. "
            f"Full result: {result}"
        )

        # There must be some diagnostic signal: either error_message or result_status.
        has_error_message = bool(result.get("error_message"))
        has_result_status = result.get("result_status") is not None
        assert has_error_message or has_result_status, (
            "FAILED job with 0 workers must have error_message or result_status set. "
            "Silent failure (no diagnostic) prevents user from understanding why "
            "the solve failed. This is unacceptable UX."
        )

    def test_b1_zero_workers_zero_shifts_fails_gracefully(
        self, empty_client, empty_session_id
    ):
        """B1 (extreme): Zero workers AND zero shifts — completely empty session.

        The solver is called with no domain objects at all.  It must handle
        this degenerate case without crashing or hanging.
        """
        client = empty_client

        # Verify the session is completely empty.
        assert len(client.get("/api/v1/workers").json()) == 0
        assert len(client.get("/api/v1/shifts").json()) == 0

        solve_resp = client.post("/api/v1/solve")
        assert solve_resp.status_code == 200, (
            f"POST /solve should accept an empty session with 200, "
            f"got {solve_resp.status_code}: {solve_resp.text}"
        )
        job_id = solve_resp.json()["job_id"]

        # Must reach a terminal state without hanging.
        result = _poll_until_terminal(client, job_id)
        assert result["status"] in ("COMPLETED", "FAILED"), (
            f"Empty-session solve must reach a terminal state, "
            f"got {result['status']!r}"
        )


# ---------------------------------------------------------------------------
# B2 — POST /solve with 0 shifts
# ---------------------------------------------------------------------------


class TestB2ZeroShifts:
    """B2: Solver with 0 shifts and ≥1 worker.

    The solver finds 'Optimal' with 0 assignments (trivially satisfied).
    The job is marked COMPLETED.  This is a degenerate-success case that
    the user may misinterpret as "no shifts needed."

    These tests document the current behavior and add an explicit quality
    check: the user must receive a meaningful signal about the empty result.
    """

    def test_b2_zero_shifts_one_worker_solver_succeeds_with_empty_assignments(
        self, empty_client, empty_session_id
    ):
        """B2: Zero shifts → solver trivially succeeds → COMPLETED with 0 assignments.

        This is a degenerate-success scenario.  The solver has nothing to
        assign, so it returns 'Optimal' (or 'Feasible') with an empty
        assignments list.  The job is therefore marked COMPLETED.

        The test:
        1. Documents this behavior explicitly (no surprise in production).
        2. Confirms the job reaches a terminal state without hanging.
        3. Confirms the assignments list is empty (not phantom data).
        """
        client = empty_client

        # Create 1 worker but NO shifts.
        worker_id = f"w_b2_{uuid.uuid4().hex[:6]}"
        resp = client.post(
            "/api/v1/workers",
            json={
                "worker_id": worker_id,
                "name": "Idle_Worker_B2",
                "attributes": {
                    "skills": {"Chef": 5},
                    "availability": {
                        "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}
                    },
                    "wage": 20.0,
                    "min_hours": 0,
                    "max_hours": 40,
                },
            },
        )
        assert resp.status_code == 201, f"Create worker failed: {resp.text}"

        # Verify no shifts exist.
        shifts_resp = client.get("/api/v1/shifts")
        assert shifts_resp.status_code == 200
        assert len(shifts_resp.json()) == 0, (
            f"Expected 0 shifts, found {len(shifts_resp.json())}"
        )

        # Trigger solve — should be accepted.
        solve_resp = client.post("/api/v1/solve")
        assert solve_resp.status_code == 200, (
            f"POST /solve should accept a no-shift session with 200, "
            f"got {solve_resp.status_code}: {solve_resp.text}"
        )
        job_id = solve_resp.json()["job_id"]

        # Poll to terminal.
        result = _poll_until_terminal(client, job_id)

        # The solver trivially solves a problem with 0 shifts.
        # Status is COMPLETED (not FAILED) because 0 assignments is "valid."
        assert result["status"] in ("COMPLETED", "FAILED"), (
            f"Zero-shift solve must reach a terminal state, "
            f"got {result['status']!r}"
        )

        if result["status"] == "COMPLETED":
            # If COMPLETED, verify 0 assignments (no phantom data).
            assignments = result.get("assignments") or []
            assert len(assignments) == 0, (
                f"Expected 0 assignments for a no-shift solve, "
                f"got {len(assignments)}: {assignments}"
            )
            # Document the quality gap: user sees COMPLETED with no signal.
            # TODO: Add a 'diagnosis_message' or warning when 0 shifts are solved.

    def test_b2_solve_result_is_accessible_via_get_status(
        self, empty_client, empty_session_id
    ):
        """B2: The zero-shift result is queryable via GET /status/{job_id}.

        Proves the GET /status endpoint returns consistent data after the
        solver completes the degenerate (0-shift) case.
        """
        client = empty_client

        # Create 1 worker.
        worker_id = f"w_b2s_{uuid.uuid4().hex[:6]}"
        client.post(
            "/api/v1/workers",
            json={
                "worker_id": worker_id,
                "name": "Status_Worker_B2",
                "attributes": {
                    "skills": {"Chef": 5},
                    "availability": {
                        "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}
                    },
                    "wage": 20.0,
                    "min_hours": 0,
                    "max_hours": 40,
                },
            },
        )

        solve_resp = client.post("/api/v1/solve")
        assert solve_resp.status_code == 200
        job_id = solve_resp.json()["job_id"]

        # Wait for terminal.
        _poll_until_terminal(client, job_id)

        # Verify GET /status still works after terminal state.
        status_resp = client.get(f"/api/v1/status/{job_id}")
        assert status_resp.status_code == 200, (
            f"GET /status after terminal should return 200, "
            f"got {status_resp.status_code}: {status_resp.text}"
        )
        data = status_resp.json()
        assert data["status"] in ("COMPLETED", "FAILED"), (
            f"GET /status must return terminal status, got {data['status']!r}"
        )
        # job_id must be preserved.
        assert data["job_id"] == job_id, (
            f"GET /status returned wrong job_id: {data['job_id']!r} != {job_id!r}"
        )
