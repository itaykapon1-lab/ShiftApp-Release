"""
TRUE END-TO-END SOLVE JOURNEY TEST
====================================

ZERO MOCKS on business logic — This test exercises the REAL production path:

    TestClient  →  FastAPI Router  →  SQLAlchemy Repository
        →  DB (in-memory SQLite)  →  SolverService.start_job()
            →  ThreadPoolExecutor  →  run_solver_in_process()
                →  OR-Tools Solver  →  DB write  →  Status poll

WHY ThreadPoolExecutor INSTEAD OF ProcessPoolExecutor?
    On Windows, ProcessPoolExecutor uses 'spawn' — it creates a fresh
    Python interpreter that re-imports every module.  This means:
    - The child process gets its OWN app.db.session.SessionLocal()
    - That SessionLocal points at the production DB (scheduler.db),
      NOT the test's in-memory DB

    Using ThreadPoolExecutor solves this: threads share the same
    process memory, so the overridden SessionLocal is visible.

    We patch ONLY `services.solver_service.get_executor` to return a
    ThreadPoolExecutor.  This is an INFRASTRUCTURE swap, not a
    business-logic mock.  The actual solver code path — repository reads,
    domain model construction, OR-Tools solving, result persistence —
    runs 100% real.

WHAT THIS TEST PROVES:
    ✅ Worker & Shift creation via real API + real DB commit
    ✅ Real SolverJobStore creates PENDING job in DB
    ✅ Real run_solver_in_process() reads workers/shifts from DB
    ✅ Real OR-Tools solver runs and finds assignments
    ✅ Real result persistence back to solver_jobs table
    ✅ Status polling reads COMPLETED status from DB
    ✅ Assignments contain correct worker/shift names
    ✅ Skill-to-shift matching is mathematically correct
    ✅ Canonical Week dates pass the pre-flight check
"""

import time
import uuid
import concurrent.futures

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from data.base import Base
from app.db.session import get_db
from api.routes import router as api_router
from api.routes_constraints_schema import router as constraints_schema_router
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture(scope="function")
def e2e_engine():
    """Create an in-memory SQLite engine shared across threads via StaticPool."""
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def e2e_session_factory(e2e_engine):
    """Session factory bound to our test engine."""
    return sessionmaker(bind=e2e_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def e2e_session_id():
    """Generate a valid UUIDv4 session ID (required by api.deps)."""
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def e2e_client(e2e_engine, e2e_session_factory, e2e_session_id):
    """Build a fully wired TestClient with a ThreadPoolExecutor for the solver.

    Wiring:
    1. Override get_db so all API routes use the in-memory test DB.
    2. Override app.db.session.SessionLocal so SolverService/SolverJobStore
       (which call SessionLocal() directly) also use the test DB.
    3. Swap ProcessPoolExecutor → ThreadPoolExecutor so run_solver_in_process()
       runs in a thread (same process = same SessionLocal).
    4. Set session_id cookie so every request scopes to our test session.
    """
    import app.db.session as session_mod
    import services.solver_service as solver_mod

    # ── Save originals ──
    orig_session_local_mod = session_mod.SessionLocal
    orig_session_local_solver = solver_mod.SessionLocal
    orig_get_executor = solver_mod.get_executor
    orig_executor = solver_mod._executor

    # ── Redirect SessionLocal to the test DB ──
    # CRITICAL: solver_service.py does `from app.db.session import SessionLocal`
    # which creates a LOCAL name binding.  Patching only session_mod.SessionLocal
    # doesn't affect the solver's copy — we must patch BOTH.
    session_mod.SessionLocal = e2e_session_factory
    solver_mod.SessionLocal = e2e_session_factory

    # ── Swap to ThreadPoolExecutor ──
    # On Windows, ProcessPoolExecutor spawns a new interpreter that can't see
    # our in-memory DB.  ThreadPoolExecutor runs in the same process, sharing
    # the patched SessionLocal.  This is an infrastructure swap, not a
    # business-logic mock — the solver code runs 100% real.
    thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    solver_mod.get_executor = lambda: thread_executor
    solver_mod._executor = None  # Reset any cached ProcessPoolExecutor

    # ── Build FastAPI app with get_db override ──
    app = FastAPI()
    app.include_router(api_router)
    app.include_router(constraints_schema_router, prefix="/api/v1")

    def override_get_db():
        db = e2e_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app, cookies={"session_id": e2e_session_id}) as tc:
            yield tc
    finally:
        # ── Cleanup: restore all originals ──
        app.dependency_overrides.clear()
        thread_executor.shutdown(wait=True)
        session_mod.SessionLocal = orig_session_local_mod
        solver_mod.SessionLocal = orig_session_local_solver
        solver_mod.get_executor = orig_get_executor
        solver_mod._executor = orig_executor


# ============================================================================
# HELPERS
# ============================================================================

# Canonical Week: Monday = 2024-01-01, Tuesday = 2024-01-02, etc.
CANONICAL_MONDAY_8AM = "2024-01-01T08:00:00"
CANONICAL_MONDAY_4PM = "2024-01-01T16:00:00"

POLL_INTERVAL_SECONDS = 0.3
POLL_TIMEOUT_SECONDS = 15


def _make_worker_payload(worker_id: str, name: str, skills: dict, days: list):
    """Build a WorkerCreate-compatible JSON payload."""
    availability = {}
    for day in days:
        availability[day] = {"timeRange": "08:00-16:00", "preference": "HIGH"}

    return {
        "worker_id": worker_id,
        "name": name,
        "attributes": {
            "skills": skills,
            "availability": availability,
            "wage": 20.0,
            "min_hours": 0,
            "max_hours": 40,
        },
    }


def _make_shift_payload(
    shift_id: str,
    name: str,
    start_time: str,
    end_time: str,
    task_name: str,
    required_skill: str,
    skill_level: int,
    worker_count: int = 1,
):
    """Build a ShiftCreate-compatible JSON payload."""
    return {
        "shift_id": shift_id,
        "name": name,
        "start_time": start_time,
        "end_time": end_time,
        "tasks_data": {
            "tasks": [
                {
                    "task_id": f"task_{shift_id}",
                    "name": task_name,
                    "options": [
                        {
                            "preference_score": 0,
                            "requirements": [
                                {
                                    "count": worker_count,
                                    "required_skills": {required_skill: skill_level},
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _poll_until_terminal(client, job_id: str, timeout: float = POLL_TIMEOUT_SECONDS):
    """Poll GET /api/v1/status/{job_id} until COMPLETED or FAILED.

    Returns the terminal status response dict.
    Fails cleanly with pytest.fail() instead of hanging forever.
    """
    deadline = time.time() + timeout
    last_status = None

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
        f"Solver did not reach a terminal status within {timeout}s. "
        f"Last polled status: {last_status}"
    )


# ============================================================================
# THE TEST
# ============================================================================


class TestTrueSolveJourney:
    """True end-to-end integration test: no mocks on business logic.

    Exercises the full production code path through 2 workers, 2 shifts,
    and the real OR-Tools solver, verifying skill-correct assignments.
    """

    def test_full_journey_creates_valid_assignments(
        self, e2e_client, e2e_session_id
    ):
        """
        Complete user journey:

        1. POST /workers  → Create 2 workers with distinct skills
        2. POST /shifts   → Create 2 shifts requiring those skills
        3. POST /solve    → Trigger real solver (runs in ThreadPoolExecutor)
        4. GET  /status   → Poll until COMPLETED
        5. VERIFY         → Assignments exist and are skill-correct

        Data Design (deterministic skill matching):
        ┌──────────────┬────────────┬──────────────────────────┐
        │ Entity       │ Skill      │ Canonical Time           │
        ├──────────────┼────────────┼──────────────────────────┤
        │ Alice (W)    │ Cook Lv5   │ MON+TUE 08:00–16:00     │
        │ Bob   (W)    │ Waiter Lv3 │ MON+TUE 08:00–16:00     │
        │ Kitchen (S)  │ Cook Lv3   │ MON 08:00–16:00         │
        │ Service (S)  │ Waiter Lv2 │ MON 08:00–16:00         │
        └──────────────┴────────────┴──────────────────────────┘

        Expected: Alice → Kitchen, Bob → Service (deterministic).
        """
        client = e2e_client

        # ── STEP 1: Create workers ─────────────────────────────────
        alice_id = f"w_alice_{uuid.uuid4().hex[:6]}"
        bob_id = f"w_bob_{uuid.uuid4().hex[:6]}"

        alice = _make_worker_payload(
            worker_id=alice_id,
            name="Alice_E2E",
            skills={"Cook": 5},
            days=["MON", "TUE"],
        )
        bob = _make_worker_payload(
            worker_id=bob_id,
            name="Bob_E2E",
            skills={"Waiter": 3},
            days=["MON", "TUE"],
        )

        r1 = client.post("/api/v1/workers", json=alice)
        assert r1.status_code == 201, f"Create Alice failed: {r1.text}"

        r2 = client.post("/api/v1/workers", json=bob)
        assert r2.status_code == 201, f"Create Bob failed: {r2.text}"

        # Sanity: both workers are persisted and visible
        workers_resp = client.get("/api/v1/workers")
        assert workers_resp.status_code == 200
        worker_names = {w["name"] for w in workers_resp.json()}
        assert "Alice_E2E" in worker_names, f"Alice not in GET /workers: {worker_names}"
        assert "Bob_E2E" in worker_names, f"Bob not in GET /workers: {worker_names}"

        # ── STEP 2: Create shifts ──────────────────────────────────
        kitchen_id = f"s_kitchen_{uuid.uuid4().hex[:6]}"
        service_id = f"s_service_{uuid.uuid4().hex[:6]}"

        shift_kitchen = _make_shift_payload(
            shift_id=kitchen_id,
            name="Monday_Kitchen_E2E",
            start_time=CANONICAL_MONDAY_8AM,
            end_time=CANONICAL_MONDAY_4PM,
            task_name="Kitchen Duty",
            required_skill="Cook",
            skill_level=3,
            worker_count=1,
        )
        shift_service = _make_shift_payload(
            shift_id=service_id,
            name="Monday_Service_E2E",
            start_time=CANONICAL_MONDAY_8AM,
            end_time=CANONICAL_MONDAY_4PM,
            task_name="Table Service",
            required_skill="Waiter",
            skill_level=2,
            worker_count=1,
        )

        r3 = client.post("/api/v1/shifts", json=shift_kitchen)
        assert r3.status_code == 201, f"Create kitchen shift failed: {r3.text}"

        r4 = client.post("/api/v1/shifts", json=shift_service)
        assert r4.status_code == 201, f"Create service shift failed: {r4.text}"

        # Sanity: both shifts are persisted and visible
        shifts_resp = client.get("/api/v1/shifts")
        assert shifts_resp.status_code == 200
        shift_names = {s["name"] for s in shifts_resp.json()}
        assert "Monday_Kitchen_E2E" in shift_names
        assert "Monday_Service_E2E" in shift_names

        # ── STEP 3: Trigger solve ──────────────────────────────────
        solve_resp = client.post("/api/v1/solve")
        assert solve_resp.status_code == 200, (
            f"Solve trigger failed ({solve_resp.status_code}): {solve_resp.text}"
        )
        job_id = solve_resp.json()["job_id"]
        assert job_id, "No job_id returned from /solve"

        # ── STEP 4: Poll until completion (strict timeout) ─────────
        result = _poll_until_terminal(client, job_id)
        status = result["status"]

        assert status == "COMPLETED", (
            f"Solver did not complete successfully. "
            f"Status: {status}, Error: {result.get('error_message')}"
        )

        # ── STEP 5: Verify business value ──────────────────────────
        # 5a. Solver found an optimal/feasible solution
        result_status = result.get("result_status")
        assert result_status in ("Optimal", "Feasible"), (
            f"Expected Optimal or Feasible, got: {result_status}"
        )

        # 5b. Exactly 2 assignments (one per shift, one worker each)
        assignments = result.get("assignments", [])
        assert len(assignments) == 2, (
            f"Expected exactly 2 assignments, got {len(assignments)}. "
            f"Assignments: {assignments}"
        )

        # 5c. Both workers are assigned
        assigned_workers = {a["worker_name"] for a in assignments}
        assert "Alice_E2E" in assigned_workers, (
            f"Alice not assigned: {assigned_workers}"
        )
        assert "Bob_E2E" in assigned_workers, (
            f"Bob not assigned: {assigned_workers}"
        )

        # 5d. Both shifts have an assignee
        assigned_shifts = {a["shift_name"] for a in assignments}
        assert "Monday_Kitchen_E2E" in assigned_shifts, (
            f"Kitchen shift has no assignee: {assigned_shifts}"
        )
        assert "Monday_Service_E2E" in assigned_shifts, (
            f"Service shift has no assignee: {assigned_shifts}"
        )

        # 5e. SKILL-CORRECT PAIRING (the mathematical proof)
        #     Alice (Cook Lv5) can ONLY satisfy Cook Lv3 requirement
        #     Bob (Waiter Lv3) can ONLY satisfy Waiter Lv2 requirement
        for a in assignments:
            if a["worker_name"] == "Alice_E2E":
                assert a["shift_name"] == "Monday_Kitchen_E2E", (
                    f"Alice (Cook) assigned to wrong shift: {a['shift_name']}"
                )
            elif a["worker_name"] == "Bob_E2E":
                assert a["shift_name"] == "Monday_Service_E2E", (
                    f"Bob (Waiter) assigned to wrong shift: {a['shift_name']}"
                )

        # 5f. Valid objective value
        obj_value = result.get("objective_value")
        assert obj_value is not None, "Missing objective_value in result"
