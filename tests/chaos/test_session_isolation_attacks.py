"""Chaos tests: Session isolation — security surface (D1, D2).

PILLAR 4 of the Backend Testing Roadmap — scenarios D1 and D2.

D1: Session A creates a solve job → Session B tries GET /status/{job_id}.
    Expected: 404 (cross-session access is denied by SolverService.get_job_status).
    Currently untested — a refactor could silently break this security invariant.

D2: Blocked session IDs ('default', 'null', '', 'undefined') are rejected.
    Expected: each request with a blocked ID receives a fresh UUID session,
    making data non-persistent across requests.
    Currently untested — the BLOCKED_SESSION_IDS set could be modified without
    CI detection.

These tests use the same infrastructure pattern as the chaos suite:
ProcessPoolExecutor → ThreadPoolExecutor, SessionLocal redirected to test DB.
"""

import concurrent.futures
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
from services.solver_service import SolverJobStore
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


pytestmark = pytest.mark.chaos


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def iso_engine():
    """Isolated in-memory SQLite engine for session isolation tests."""
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def iso_session_factory(iso_engine):
    """Session factory bound to the test engine."""
    return sessionmaker(bind=iso_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def iso_client(iso_engine, iso_session_factory):
    """Fully wired TestClient with ThreadPoolExecutor (NO pre-set session cookie).

    This fixture deliberately does NOT set a session_id cookie so individual
    tests can supply different session IDs per request, exercising isolation.

    Infrastructure swaps (NOT business-logic mocks):
    1. session_mod.SessionLocal → test factory
    2. solver_mod.SessionLocal  → test factory
    3. solver_mod.get_executor  → ThreadPoolExecutor(max_workers=2)
    """
    orig_session_local_mod = session_mod.SessionLocal
    orig_session_local_solver = solver_mod.SessionLocal
    orig_get_executor = solver_mod.get_executor
    orig_executor = solver_mod._executor

    session_mod.SessionLocal = iso_session_factory
    solver_mod.SessionLocal = iso_session_factory

    thread_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
    solver_mod.get_executor = lambda: thread_executor
    solver_mod._executor = None

    app = FastAPI()
    app.include_router(api_router)
    app.include_router(constraints_schema_router, prefix="/api/v1")

    def override_get_db():
        db = iso_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        # No cookies pre-set — tests supply them explicitly.
        with TestClient(app) as tc:
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


def _make_cookies(session_id: str) -> dict:
    return {"session_id": session_id}


def _make_valid_session_id() -> str:
    """Return a valid UUID4 session ID."""
    return str(uuid.uuid4())


def _create_pending_job(iso_session_factory, session_id: str) -> str:
    """Create a solver job directly in the DB and return the job_id.

    Uses SolverJobStore to bypass the HTTP layer — we only need the job
    record for isolation testing, not a real solve.
    """
    db = iso_session_factory()
    try:
        job_id = SolverJobStore.create_job(db, session_id)
        db.commit()  # create_job only flushes; persist before closing session
        return job_id
    finally:
        db.close()


# ---------------------------------------------------------------------------
# D1 — Cross-session job access returns 404
# ---------------------------------------------------------------------------


class TestCrossSessionJobAccess:
    """D1: A session cannot query solver jobs that belong to another session.

    The SolverService.get_job_status() method checks:
        if job_data.get("session_id") != session_id:
            return None

    When the route receives None, it should return HTTP 404.

    This is the correct behavior — but it is currently untested.  Any
    refactor that removes the ownership check would silently expose all
    solver results to any authenticated session.
    """

    def test_d1_session_b_cannot_access_session_a_job(
        self, iso_client, iso_session_factory
    ):
        """D1: GET /status/{job_id} with wrong session_id returns 404.

        Setup:
        - Session A creates a solver job (job_id_a).
        - Session B (a different UUID) attempts GET /status/{job_id_a}.

        Expected: HTTP 404 (job not visible to Session B).
        This enforces multi-tenant data isolation at the job level.
        """
        client = iso_client

        session_a_id = _make_valid_session_id()
        session_b_id = _make_valid_session_id()
        assert session_a_id != session_b_id, "Test setup: session IDs must differ"

        # Session A creates a job.
        job_id_a = _create_pending_job(iso_session_factory, session_a_id)
        assert job_id_a, "Job ID must be non-empty"

        # Session A can query its own job.
        resp_a = client.get(
            f"/api/v1/status/{job_id_a}",
            cookies=_make_cookies(session_a_id),
        )
        assert resp_a.status_code == 200, (
            f"Session A should be able to access its own job {job_id_a!r}, "
            f"got {resp_a.status_code}: {resp_a.text}"
        )
        assert resp_a.json()["job_id"] == job_id_a

        # Session B attempts to access Session A's job.
        resp_b = client.get(
            f"/api/v1/status/{job_id_a}",
            cookies=_make_cookies(session_b_id),
        )
        assert resp_b.status_code == 404, (
            f"Session B must NOT be able to access Session A's job. "
            f"Expected HTTP 404, got {resp_b.status_code}: {resp_b.text}. "
            "SECURITY VIOLATION: cross-session job access is unauthorized."
        )

    def test_d1_session_can_query_own_jobs_but_not_others(
        self, iso_client, iso_session_factory
    ):
        """D1: Each session can see its own jobs and only its own jobs.

        Creates jobs for two different sessions and verifies that each session
        can access its own jobs (200) and cannot access the other's (404).
        """
        client = iso_client

        session_x_id = _make_valid_session_id()
        session_y_id = _make_valid_session_id()

        job_x = _create_pending_job(iso_session_factory, session_x_id)
        job_y = _create_pending_job(iso_session_factory, session_y_id)

        # Session X: own job accessible.
        resp = client.get(
            f"/api/v1/status/{job_x}",
            cookies=_make_cookies(session_x_id),
        )
        assert resp.status_code == 200, (
            f"Session X should access its own job, got {resp.status_code}"
        )

        # Session X: other session's job not accessible.
        resp = client.get(
            f"/api/v1/status/{job_y}",
            cookies=_make_cookies(session_x_id),
        )
        assert resp.status_code == 404, (
            f"Session X must not access Session Y's job, got {resp.status_code}"
        )

        # Session Y: own job accessible.
        resp = client.get(
            f"/api/v1/status/{job_y}",
            cookies=_make_cookies(session_y_id),
        )
        assert resp.status_code == 200, (
            f"Session Y should access its own job, got {resp.status_code}"
        )

        # Session Y: other session's job not accessible.
        resp = client.get(
            f"/api/v1/status/{job_x}",
            cookies=_make_cookies(session_y_id),
        )
        assert resp.status_code == 404, (
            f"Session Y must not access Session X's job, got {resp.status_code}"
        )

    def test_d1_nonexistent_job_id_returns_404(self, iso_client):
        """D1 (boundary): A completely non-existent job_id returns 404.

        Ensures the 404 path works for jobs that never existed, not just for
        cross-session access attempts.
        """
        client = iso_client
        session_id = _make_valid_session_id()
        fake_job_id = str(uuid.uuid4())

        resp = client.get(
            f"/api/v1/status/{fake_job_id}",
            cookies=_make_cookies(session_id),
        )
        assert resp.status_code == 404, (
            f"Nonexistent job_id should return 404, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# D2 — Blocked session IDs generate new UUID
# ---------------------------------------------------------------------------


class TestBlockedSessionIds:
    """D2: Session IDs in the blocklist must not be accepted.

    The BLOCKED_SESSION_IDS set in api/deps.py contains:
        {"default", "test", "", "null", "undefined", "none"}

    When a blocked ID is received, get_session_id() generates a new UUID
    and stores it in request.state.session_id.  This means:
    - Each request with a blocked ID gets a DIFFERENT generated UUID.
    - Data posted under "default" is not retrievable in the next request.
    - The blocked ID never leaks into the database as a session_id.
    """

    @pytest.mark.parametrize("blocked_id", ["default", "null", "undefined", "none"])
    def test_d2_blocked_session_id_does_not_persist_data_between_requests(
        self, iso_client, blocked_id
    ):
        """D2: Data posted with a blocked session ID is not retrievable in the
        next request using the same blocked ID (because each request gets a
        different auto-generated UUID).

        This confirms the intent of BLOCKED_SESSION_IDS: prevent clients from
        accidentally sharing the 'default' namespace, which would cause data
        leakage between unrelated users.
        """
        client = iso_client
        cookies = _make_cookies(blocked_id)

        worker_id = f"w_{uuid.uuid4().hex[:8]}"
        worker_payload = {
            "worker_id": worker_id,
            "name": f"Blocked_Session_Worker_{blocked_id}",
            "attributes": {
                "skills": {"Chef": 5},
                "availability": {
                    "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}
                },
                "wage": 20.0,
                "min_hours": 0,
                "max_hours": 40,
            },
        }

        # Post a worker with the blocked session ID.
        # The server will assign a random UUID to this request.
        post_resp = client.post(
            "/api/v1/workers",
            json=worker_payload,
            cookies=cookies,
        )
        # The POST itself may succeed (the server assigns a new UUID for this req).
        # We don't assert the status here — the critical test is the GET below.

        # GET /workers with the same blocked ID.
        # The server will assign a DIFFERENT random UUID for this second request.
        # Therefore, the worker posted under the first UUID is not visible here.
        get_resp = client.get("/api/v1/workers", cookies=cookies)
        assert get_resp.status_code == 200
        workers = get_resp.json()

        # The posted worker must NOT appear — each request got a different UUID.
        visible_worker_ids = {w["worker_id"] for w in workers}
        assert worker_id not in visible_worker_ids, (
            f"Worker posted under blocked session ID '{blocked_id}' must NOT be "
            f"visible in a second request with the same blocked ID. "
            f"If visible, the blocked ID was accepted and persisted — "
            f"BLOCKED_SESSION_IDS is not enforced."
        )

    def test_d2_empty_session_id_cookie_generates_new_session(self, iso_client):
        """D2: A missing or empty session_id cookie generates a new UUID session.

        A request with no session cookie should work (200) because get_session_id()
        generates a fresh UUID.  The response body should be valid JSON.
        """
        client = iso_client

        # Request with NO session cookie.
        resp = client.get("/api/v1/workers")
        assert resp.status_code == 200, (
            f"Request with no session cookie should succeed (200), "
            f"got {resp.status_code}: {resp.text}"
        )
        # Response is a JSON list (empty for a fresh session).
        assert isinstance(resp.json(), list), (
            f"Expected JSON list for fresh session, got: {resp.json()!r}"
        )

    def test_d2_valid_uuid_session_id_is_accepted(self, iso_client):
        """D2 (control): A valid UUID4 session ID is accepted and used consistently.

        Confirms that the UUID validation in get_session_id() allows proper
        UUIDs while blocking the reserved names.
        """
        client = iso_client
        valid_session = _make_valid_session_id()
        cookies = _make_cookies(valid_session)

        # Post a worker under the valid session.
        worker_id = f"w_{uuid.uuid4().hex[:8]}"
        post_resp = client.post(
            "/api/v1/workers",
            json={
                "worker_id": worker_id,
                "name": "Valid_Session_Worker",
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
            cookies=cookies,
        )
        assert post_resp.status_code == 201, (
            f"Valid UUID session should allow worker creation, "
            f"got {post_resp.status_code}: {post_resp.text}"
        )

        # GET /workers with the SAME session cookie should see the worker.
        get_resp = client.get("/api/v1/workers", cookies=cookies)
        assert get_resp.status_code == 200
        workers = get_resp.json()
        visible_ids = {w["worker_id"] for w in workers}
        assert worker_id in visible_ids, (
            f"Worker {worker_id!r} posted under valid session {valid_session!r} "
            f"must be visible in GET /workers with the same session. "
            f"Visible workers: {visible_ids}"
        )
