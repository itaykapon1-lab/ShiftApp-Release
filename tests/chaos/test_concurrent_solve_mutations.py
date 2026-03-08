"""Chaos tests: Concurrent solve mutations (CHAOS-01, CHAOS-02, CHAOS-03).

These tests prove that the solver and API handle concurrent state mutations
gracefully — without HTTP 500 errors, data corruption, or stuck jobs.

ZERO BUSINESS-LOGIC MOCKS.  The real OR-Tools CP-SAT solver runs on every
test.  The only infrastructure swap is ProcessPoolExecutor → ThreadPoolExecutor
so the solver thread shares the in-memory test database with the API layer.

Architecture:
    TestClient (HTTP layer)
        → FastAPI router
        → SQLAlchemy repository (in-memory SQLite, StaticPool)
        → SolverService.start_job() → ThreadPoolExecutor
            → run_solver_in_process() → OR-Tools CP-SAT

CHAOS-01 — Concurrent solve + shift delete:
    Start a real solve job.  While the solver thread is in-flight, send a
    DELETE for one of the shifts.  Prove the system handles the race
    gracefully and leaves the database consistent.

CHAOS-02 — Concurrent solve + worker delete:
    Start a real solve job, then immediately delete the only eligible worker.
    Prove the solver reaches COMPLETED or FAILED (never hangs) and the DB
    is consistent post-race.

CHAOS-03 — Double-click solve (simultaneous POST /solve):
    Fire two POST /solve requests for the same session at the same instant.
    Prove that exactly one job record is created and the system returns 409
    Conflict for the duplicate rather than spawning a second solver process.
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
from data.models import ShiftModel, SolverJobModel, WorkerModel
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


# ==============================================================================
# Constants
# ==============================================================================

# Canonical Epoch Week: Monday = 2024-01-01, Tuesday = 2024-01-02
CANONICAL_MONDAY_8AM: str = "2024-01-01T08:00:00"
CANONICAL_MONDAY_4PM: str = "2024-01-01T16:00:00"
CANONICAL_TUESDAY_9AM: str = "2024-01-02T09:00:00"
CANONICAL_TUESDAY_5PM: str = "2024-01-02T17:00:00"

POLL_INTERVAL_SECONDS: float = 0.3
POLL_TIMEOUT_SECONDS: float = 25.0  # Generous budget — CI machines can be slow.


# ==============================================================================
# Module-level pytest marker
# ==============================================================================

pytestmark = pytest.mark.chaos


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture(scope="function")
def chaos_engine():
    """Create an isolated in-memory SQLite engine for chaos tests.

    StaticPool ensures every thread shares one physical connection, making
    data written by the API layer immediately visible to the solver thread.

    Yields:
        A SQLAlchemy engine backed by an in-memory SQLite database.
    """
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def chaos_session_factory(chaos_engine):
    """Session factory bound to the chaos test engine.

    Args:
        chaos_engine: The isolated SQLAlchemy engine for this test.

    Returns:
        A ``sessionmaker`` callable that produces sessions against the
        in-memory test database.
    """
    return sessionmaker(bind=chaos_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def chaos_session_id() -> str:
    """Generate a valid UUIDv4 session ID required by ``api.deps.get_session_id``.

    Returns:
        A freshly generated UUID4 string.
    """
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def chaos_client(chaos_engine, chaos_session_factory, chaos_session_id):
    """Build a fully wired TestClient with infrastructure swaps for chaos tests.

    Wiring applied (infrastructure swaps — NOT business-logic mocks):

    1. ``session_mod.SessionLocal`` → ``chaos_session_factory`` so FastAPI
       route handlers use the in-memory test database.
    2. ``solver_mod.SessionLocal`` → same factory, because
       ``solver_service.py`` captures ``SessionLocal`` by name at import
       time and must be patched at its own local reference.
    3. ``solver_mod.get_executor`` → ``ThreadPoolExecutor(max_workers=2)``.
       On Windows, ``ProcessPoolExecutor`` spawns a fresh interpreter that
       cannot see the in-memory DB.  Threads share process memory, so the
       patched ``SessionLocal`` remains visible to ``run_solver_in_process``.
       This is a transport swap; the solver code path runs 100 % real.
    4. The ``session_id`` cookie is pre-set on every request so all HTTP
       calls scope to the same test session.

    Args:
        chaos_engine: Isolated SQLAlchemy engine.
        chaos_session_factory: Session factory bound to ``chaos_engine``.
        chaos_session_id: UUID4 session identifier cookie value.

    Yields:
        A ``TestClient`` pre-configured with the chaos session cookie.
    """
    # Save originals before patching.
    orig_session_local_mod = session_mod.SessionLocal
    orig_session_local_solver = solver_mod.SessionLocal
    orig_get_executor = solver_mod.get_executor
    orig_executor = solver_mod._executor

    # Redirect SessionLocal references to the test DB.
    session_mod.SessionLocal = chaos_session_factory
    solver_mod.SessionLocal = chaos_session_factory

    # Swap to ThreadPoolExecutor.  Two workers: one for the solver background
    # task and one spare for CHAOS-03's second simultaneous submission.
    thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    solver_mod.get_executor = lambda: thread_executor
    solver_mod._executor = None  # Invalidate any cached ProcessPoolExecutor.

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(constraints_schema_router, prefix="/api/v1")

    def override_get_db():
        """Yield a fresh session from the test factory for every request."""
        db = chaos_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app, cookies={"session_id": chaos_session_id}) as tc:
            yield tc
    finally:
        # Restore all originals so other tests are unaffected.
        app.dependency_overrides.clear()
        thread_executor.shutdown(wait=True)
        session_mod.SessionLocal = orig_session_local_mod
        solver_mod.SessionLocal = orig_session_local_solver
        solver_mod.get_executor = orig_get_executor
        solver_mod._executor = orig_executor


# ==============================================================================
# Helpers
# ==============================================================================


def _make_worker_payload(
    worker_id: str,
    name: str,
    skills: dict,
    days: list[str],
) -> dict:
    """Build a ``WorkerCreate``-compatible JSON payload.

    Args:
        worker_id: Unique string identifier for the worker.
        name: Human-readable display name.
        skills: Mapping of skill name → proficiency level (1–10).
        days: Day-code list (e.g. ``["MON", "TUE"]``) for availability.
            Each day receives the time range ``08:00-16:00`` at HIGH preference.

    Returns:
        A dict suitable for ``POST /api/v1/workers``.
    """
    availability = {
        day: {"timeRange": "08:00-16:00", "preference": "HIGH"} for day in days
    }
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
) -> dict:
    """Build a ``ShiftCreate``-compatible JSON payload.

    Args:
        shift_id: Unique string identifier for the shift.
        name: Human-readable shift name.
        start_time: ISO 8601 datetime string (use canonical epoch dates).
        end_time: ISO 8601 datetime string.
        task_name: Descriptive name of the task within the shift.
        required_skill: Skill name that fulfils the task.
        skill_level: Minimum proficiency level required.
        worker_count: Number of workers needed for this task option.

    Returns:
        A dict suitable for ``POST /api/v1/shifts``.
    """
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


def _poll_until_terminal(
    client: TestClient,
    job_id: str,
    timeout: float = POLL_TIMEOUT_SECONDS,
) -> dict:
    """Poll ``GET /api/v1/status/{job_id}`` until COMPLETED or FAILED.

    Args:
        client: The ``TestClient`` to use for polling requests.
        job_id: The solver job identifier returned by ``POST /solve``.
        timeout: Maximum seconds to wait before declaring the test failed.

    Returns:
        The terminal job status response dict from the final successful poll.

    Raises:
        pytest.fail: If the job has not reached a terminal state within ``timeout``.
    """
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


def _fresh_db_query(session_factory, model_cls, **filter_kwargs) -> list:
    """Query the database with a fresh session, bypassing the ORM identity map.

    Creates a new session to guarantee we read committed state from SQLite
    rather than a stale in-memory cache from a previous session.

    Args:
        session_factory: A ``sessionmaker`` callable.
        model_cls: The SQLAlchemy ORM model class to query.
        **filter_kwargs: Column-equality filters forwarded to ``filter_by()``.

    Returns:
        A list of ``model_cls`` instances matching all supplied filters.
    """
    db = session_factory()
    try:
        return db.query(model_cls).filter_by(**filter_kwargs).all()
    finally:
        db.close()


# ==============================================================================
# Tests
# ==============================================================================


class TestConcurrentSolveMutations:
    """Chaos tests for concurrent HTTP mutations against an active solve job.

    All three scenarios use the real OR-Tools CP-SAT solver.  The only
    infrastructure change is ProcessPoolExecutor → ThreadPoolExecutor so that
    the solver background thread can access the in-memory test database.
    ``SolverService``, ``SolverEngine``, and all repositories are unpatched.
    """

    def test_chaos_01_shift_delete_during_active_solve(
        self,
        chaos_client: TestClient,
        chaos_session_factory,
        chaos_session_id: str,
    ) -> None:
        """CHAOS-01: Deleting a shift while the solver runs must not corrupt state.

        Scenario:
            1. Create 1 worker (Alice, Chef Lv5) available Monday–Tuesday.
            2. Create 2 shifts — Monday Kitchen (Chef Lv3) and Tuesday Kitchen.
            3. ``POST /solve`` → real solver starts in the background thread.
            4. 50 ms later, concurrently ``DELETE /shifts/{tuesday_shift_id}``.
            5. Poll the solver job to completion.

        Acceptance criteria:
            - ``DELETE`` returns HTTP 200 (shift removed successfully).
            - ``POST /solve`` returns HTTP 200 (job accepted).
            - Solver job reaches COMPLETED or FAILED — never hangs indefinitely.
            - If FAILED, ``error_message`` is non-empty (no silent failure).
            - DB post-condition: deleted shift absent; exactly 1 ``SolverJobModel``
              row; Alice's ``WorkerModel`` row intact.

        Args:
            chaos_client: Wired ``TestClient`` with ThreadPoolExecutor solver.
            chaos_session_factory: Session factory for direct DB verification.
            chaos_session_id: UUID4 session identifier in use for this test.
        """
        client = chaos_client

        # ── Arrange: 1 worker covering both shifts ────────────────────────
        alice_id = f"w_alice_{uuid.uuid4().hex[:6]}"
        shift_monday_id = f"s_monday_{uuid.uuid4().hex[:6]}"
        shift_tuesday_id = f"s_tuesday_{uuid.uuid4().hex[:6]}"  # ← will be deleted

        resp = client.post(
            "/api/v1/workers",
            json=_make_worker_payload(
                alice_id, "Alice_C01", {"Chef": 5}, ["MON", "TUE"]
            ),
        )
        assert resp.status_code == 201, f"Create worker failed: {resp.text}"

        resp = client.post(
            "/api/v1/shifts",
            json=_make_shift_payload(
                shift_monday_id,
                "Monday_Kitchen_C01",
                CANONICAL_MONDAY_8AM,
                CANONICAL_MONDAY_4PM,
                "Kitchen AM",
                "Chef",
                3,
            ),
        )
        assert resp.status_code == 201, f"Create Monday shift failed: {resp.text}"

        resp = client.post(
            "/api/v1/shifts",
            json=_make_shift_payload(
                shift_tuesday_id,
                "Tuesday_Kitchen_C01",
                CANONICAL_TUESDAY_9AM,
                CANONICAL_TUESDAY_5PM,
                "Kitchen PM",
                "Chef",
                3,
            ),
        )
        assert resp.status_code == 201, f"Create Tuesday shift failed: {resp.text}"

        # ── Act: fire solve then concurrently delete the Tuesday shift ────
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            # Submit solve first; it enqueues the job and returns fast while
            # the real solver begins executing in the background thread.
            future_solve = pool.submit(client.post, "/api/v1/solve")
            # Brief pause: allow the solve HTTP round-trip to complete and the
            # solver thread to start loading workers/shifts from the DB.
            time.sleep(0.05)
            # Concurrently delete the Tuesday shift while the solver may be
            # mid-execution — this is the race we want to stress.
            future_delete = pool.submit(
                client.delete, f"/api/v1/shifts/{shift_tuesday_id}"
            )
            solve_resp = future_solve.result(timeout=10)
            delete_resp = future_delete.result(timeout=10)

        # ── Assert: neither HTTP operation returned 500 ───────────────────
        assert solve_resp.status_code == 200, (
            f"POST /solve returned unexpected {solve_resp.status_code}: {solve_resp.text}"
        )
        assert delete_resp.status_code == 200, (
            f"DELETE /shifts returned unexpected {delete_resp.status_code}: {delete_resp.text}"
        )

        # ── Assert: solver job reaches a clean terminal state ─────────────
        job_id: str = solve_resp.json()["job_id"]
        result = _poll_until_terminal(client, job_id)

        assert result["status"] in ("COMPLETED", "FAILED"), (
            f"Unexpected terminal status: {result['status']!r}"
        )
        if result["status"] == "FAILED" and result.get("result_status") != "Infeasible":
            # Exception-based failures must carry a non-empty error_message.
            # Graceful Infeasible results also map to FAILED status (via
            # update_job_completed), but have no error_message by design.
            assert result.get("error_message"), (
                "A FAILED solver job caused by an exception must carry a "
                "non-empty error_message. Silent exception failure is "
                "unacceptable — the user needs to know why."
            )

        # ── Assert: DB integrity post-race ────────────────────────────────
        # Deleted shift must be absent from the database.
        remaining_shifts = _fresh_db_query(
            chaos_session_factory, ShiftModel, session_id=chaos_session_id
        )
        remaining_shift_ids = {s.shift_id for s in remaining_shifts}
        assert shift_tuesday_id not in remaining_shift_ids, (
            f"Deleted shift {shift_tuesday_id!r} is still present in the DB. "
            "DELETE did not persist or was rolled back unexpectedly."
        )

        # Exactly one solver job must exist — no phantom duplicates.
        jobs = _fresh_db_query(
            chaos_session_factory, SolverJobModel, session_id=chaos_session_id
        )
        assert len(jobs) == 1, (
            f"Expected exactly 1 SolverJobModel for session, found {len(jobs)}. "
            f"Job IDs: {[j.job_id for j in jobs]}"
        )

        # Alice must still be in the DB — her DELETE was never called.
        workers = _fresh_db_query(
            chaos_session_factory, WorkerModel, session_id=chaos_session_id
        )
        worker_names = {w.name for w in workers}
        assert "Alice_C01" in worker_names, (
            f"Worker Alice_C01 unexpectedly missing post-chaos. "
            f"Workers in DB: {worker_names}"
        )

    def test_chaos_02_worker_delete_during_active_solve(
        self,
        chaos_client: TestClient,
        chaos_session_factory,
        chaos_session_id: str,
    ) -> None:
        """CHAOS-02: Deleting the sole eligible worker mid-solve must not crash.

        Scenario:
            1. Create exactly 1 worker (Bob, Waiter Lv4) — the only one
               eligible for the shift.
            2. Create 1 shift requiring Waiter Lv2.
            3. ``POST /solve`` → real solver starts.
            4. 50 ms later, concurrently ``DELETE /workers/{bob_id}``.
            5. Poll solver to completion.

        Acceptance criteria:
            - ``DELETE`` returns HTTP 200.
            - ``POST /solve`` returns HTTP 200.
            - Solver reaches COMPLETED or FAILED — does not hang.
            - If FAILED (no eligible workers seen), ``error_message`` is set.
            - DB post-condition: Bob gone; shift still intact;
              exactly 1 ``SolverJobModel`` with the correct ``session_id``.

        Args:
            chaos_client: Wired ``TestClient`` with ThreadPoolExecutor solver.
            chaos_session_factory: Session factory for direct DB verification.
            chaos_session_id: UUID4 session identifier in use for this test.
        """
        client = chaos_client

        # ── Arrange: 1 worker, 1 shift — tight coupling ───────────────────
        bob_id = f"w_bob_{uuid.uuid4().hex[:6]}"
        shift_id = f"s_lunch_{uuid.uuid4().hex[:6]}"

        resp = client.post(
            "/api/v1/workers",
            json=_make_worker_payload(bob_id, "Bob_C02", {"Waiter": 4}, ["MON"]),
        )
        assert resp.status_code == 201, f"Create worker failed: {resp.text}"

        resp = client.post(
            "/api/v1/shifts",
            json=_make_shift_payload(
                shift_id,
                "Lunch_Service_C02",
                CANONICAL_MONDAY_8AM,
                CANONICAL_MONDAY_4PM,
                "Table Service",
                "Waiter",
                2,
            ),
        )
        assert resp.status_code == 201, f"Create shift failed: {resp.text}"

        # ── Act: fire solve then concurrently delete the only worker ──────
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_solve = pool.submit(client.post, "/api/v1/solve")
            # Allow solve to enqueue before the delete races ahead.
            time.sleep(0.05)
            future_delete = pool.submit(
                client.delete, f"/api/v1/workers/{bob_id}"
            )
            solve_resp = future_solve.result(timeout=10)
            delete_resp = future_delete.result(timeout=10)

        # ── Assert: neither HTTP operation returned 500 ───────────────────
        assert solve_resp.status_code == 200, (
            f"POST /solve returned {solve_resp.status_code}: {solve_resp.text}"
        )
        assert delete_resp.status_code == 200, (
            f"DELETE /workers returned {delete_resp.status_code}: {delete_resp.text}"
        )

        # ── Assert: solver reaches a clean terminal state ─────────────────
        job_id: str = solve_resp.json()["job_id"]
        result = _poll_until_terminal(client, job_id)

        assert result["status"] in ("COMPLETED", "FAILED"), (
            f"Unexpected terminal status: {result['status']!r}"
        )
        if result["status"] == "FAILED":
            # The solver must surface a human-readable reason, not a bare
            # exception traceback or an empty string.
            assert result.get("error_message"), (
                "FAILED job must carry a non-empty error_message. "
                "Swallowing the error silently prevents diagnosis."
            )

        # ── Assert: DB integrity post-race ────────────────────────────────
        # Bob must be gone from the workers table.
        workers = _fresh_db_query(
            chaos_session_factory, WorkerModel, session_id=chaos_session_id
        )
        worker_ids = {w.worker_id for w in workers}
        assert bob_id not in worker_ids, (
            f"Deleted worker {bob_id!r} is still present in DB after DELETE. "
            "The DELETE operation may not have committed."
        )

        # The shift must remain — only the worker was deleted.
        shifts = _fresh_db_query(
            chaos_session_factory, ShiftModel, session_id=chaos_session_id
        )
        shift_ids = {s.shift_id for s in shifts}
        assert shift_id in shift_ids, (
            f"Shift {shift_id!r} was unexpectedly removed during chaos test. "
            "Only the worker should have been affected."
        )

        # Exactly one job record — no silent duplicate spawning.
        jobs = _fresh_db_query(
            chaos_session_factory, SolverJobModel, session_id=chaos_session_id
        )
        assert len(jobs) == 1, (
            f"Expected 1 SolverJobModel, found {len(jobs)}. "
            f"IDs: {[j.job_id for j in jobs]}"
        )
        assert jobs[0].session_id == chaos_session_id, (
            f"Job session_id mismatch: {jobs[0].session_id!r} != {chaos_session_id!r}"
        )

    def test_chaos_03_simultaneous_solve_requests_prevent_duplicate_jobs(
        self,
        chaos_client: TestClient,
        chaos_session_factory,
        chaos_session_id: str,
    ) -> None:
        """CHAOS-03: Two simultaneous POST /solve requests must not spawn duplicates.

        Simulates a double-click on the "Solve" button — two HTTP POST requests
        race to ``/solve`` within the same millisecond window for the same session.

        Acceptance criteria:
            - Outcome A (expected): one request returns HTTP 200 with a ``job_id``,
              the other returns HTTP 409 Conflict.
            - Outcome B (also valid): both return 200 with the *same* ``job_id``
              (idempotent server-side deduplication).
            - Under no circumstances may both return 200 with *different* job IDs
              (this would indicate a race condition in ``SolverService.start_job``).
            - DB post-condition: exactly 1 ``SolverJobModel`` row exists for this
              session — no phantom duplicates.
            - The single surviving job reaches COMPLETED or FAILED.

        Args:
            chaos_client: Wired ``TestClient`` with ThreadPoolExecutor solver.
            chaos_session_factory: Session factory for direct DB verification.
            chaos_session_id: UUID4 session identifier in use for this test.
        """
        client = chaos_client

        # ── Arrange: minimal valid scheduling problem ─────────────────────
        worker_id = f"w_carol_{uuid.uuid4().hex[:6]}"
        shift_id = f"s_brunch_{uuid.uuid4().hex[:6]}"

        resp = client.post(
            "/api/v1/workers",
            json=_make_worker_payload(
                worker_id, "Carol_C03", {"Chef": 5, "Waiter": 3}, ["MON"]
            ),
        )
        assert resp.status_code == 201, f"Create worker failed: {resp.text}"

        resp = client.post(
            "/api/v1/shifts",
            json=_make_shift_payload(
                shift_id,
                "Brunch_C03",
                CANONICAL_MONDAY_8AM,
                CANONICAL_MONDAY_4PM,
                "Brunch Service",
                "Chef",
                2,
            ),
        )
        assert resp.status_code == 201, f"Create shift failed: {resp.text}"

        # ── Act: fire two POST /solve simultaneously ───────────────────────
        # Both threads start as close together as the GIL allows.  With SQLite's
        # serialised writes, at most one job can be committed before the other
        # thread reads the active-job guard in SolverService._has_active_job().
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(client.post, "/api/v1/solve")
            future_b = pool.submit(client.post, "/api/v1/solve")
            resp_a = future_a.result(timeout=10)
            resp_b = future_b.result(timeout=10)

        status_a, status_b = resp_a.status_code, resp_b.status_code

        # ── Assert: HTTP contract ─────────────────────────────────────────
        # The only legal combinations are (200, 409) or (200, 200) with
        # matching job IDs.  Any other combination is a bug.
        both_succeeded = status_a == 200 and status_b == 200
        one_rejected = (status_a == 200 and status_b == 409) or (
            status_a == 409 and status_b == 200
        )

        assert both_succeeded or one_rejected, (
            f"Unexpected status pair from simultaneous /solve: "
            f"({status_a}, {status_b}). "
            f"Expected (200, 409), (409, 200), or (200, 200) with same job_id."
        )

        if both_succeeded:
            # Idempotent path — server deduplicated the requests.  Both
            # responses must carry the identical job_id.
            job_id_a = resp_a.json().get("job_id")
            job_id_b = resp_b.json().get("job_id")
            assert job_id_a == job_id_b, (
                f"Two HTTP 200 responses returned DIFFERENT job_ids: "
                f"{job_id_a!r} vs {job_id_b!r}. "
                "This is a race condition — two solver processes were spawned "
                "for the same session simultaneously."
            )
            winning_job_id: str = job_id_a
        else:
            # Standard rejection path — identify winner and loser.
            winner_resp = resp_a if status_a == 200 else resp_b
            loser_resp = resp_b if status_a == 200 else resp_a

            assert loser_resp.status_code == 409, (
                f"Expected 409 Conflict for duplicate solve request, "
                f"got {loser_resp.status_code}: {loser_resp.text}"
            )
            winning_job_id = winner_resp.json()["job_id"]

        # ── Assert: exactly ONE job row in the database ───────────────────
        # This is the definitive proof that no duplicate solver was spawned.
        jobs = _fresh_db_query(
            chaos_session_factory, SolverJobModel, session_id=chaos_session_id
        )
        assert len(jobs) == 1, (
            f"Race condition detected: expected 1 SolverJobModel for session "
            f"{chaos_session_id!r}, found {len(jobs)}. "
            f"Duplicate job IDs: {[j.job_id for j in jobs]}. "
            "SolverService.start_job() does not serialise concurrent requests."
        )
        assert jobs[0].job_id == winning_job_id, (
            f"DB job_id ({jobs[0].job_id!r}) does not match the winning "
            f"HTTP response job_id ({winning_job_id!r})."
        )

        # ── Assert: surviving job reaches a terminal state ────────────────
        result = _poll_until_terminal(client, winning_job_id)
        assert result["status"] in ("COMPLETED", "FAILED"), (
            f"Surviving job {winning_job_id!r} never reached a terminal status. "
            f"Final polled status: {result['status']!r}"
        )
