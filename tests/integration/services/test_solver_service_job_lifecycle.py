"""Integration tests for solver job lifecycle persistence.

Sprint 3 hardening: extended the original PENDING-only test to cover
RUNNING, COMPLETED, and FAILED status transitions, plus field verification
on the job record at each lifecycle stage.

IMPORTANT — SessionLocal patching:
SolverJobStore.update_job_running / update_job_completed / update_job_failed
each create their OWN database session via `SessionLocal()` by design (process
isolation for the ProcessPoolExecutor solver).  In the test environment,
`SessionLocal` must be redirected to the SAME in-memory engine used by the
test session, otherwise updates go to the production scheduler.db and are
invisible to the test's DB queries.

The `lifecycle_session` fixture below handles this patching transparently.
"""

import pytest
from sqlalchemy.orm import sessionmaker

from app.schemas.job import JobStatus
from data.models import SolverJobModel
from services.solver_service import SolverJobStore
from tests.fixtures.db_fixtures import create_isolated_engine, destroy_isolated_engine


pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def lifecycle_engine():
    """Isolated in-memory SQLite engine for lifecycle tests."""
    engine = create_isolated_engine()
    yield engine
    destroy_isolated_engine(engine)


@pytest.fixture(scope="function")
def lifecycle_session_factory(lifecycle_engine):
    """Session factory bound to the lifecycle test engine."""
    return sessionmaker(bind=lifecycle_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def lifecycle_session(lifecycle_session_factory):
    """A SQLAlchemy session for lifecycle tests.

    SolverJobStore.update_job_running/completed/failed now accept db directly,
    so no SessionLocal patching is required in this fixture.

    Yields:
        tuple: (session, session_factory) so tests can open additional sessions.
    """
    session = lifecycle_session_factory()
    try:
        yield session, lifecycle_session_factory
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_job_lifecycle_transitions(lifecycle_session, session_id_factory):
    """Full PENDING → RUNNING → COMPLETED lifecycle via SolverJobStore.

    Exercises all three primary status transitions and verifies:
    - PENDING: job created with correct session_id, empty results.
    - RUNNING: started_at timestamp is set.
    - COMPLETED: status, result_status, objective_value, assignments persisted.
    """
    db, factory = lifecycle_session
    session_id = session_id_factory("solver-job")

    # ── PENDING ──────────────────────────────────────────────────────────────
    job_id = SolverJobStore.create_job(db, session_id)
    job = SolverJobStore.get_job(db, job_id)

    assert job["status"] == JobStatus.PENDING, (
        f"Freshly created job must be PENDING, got {job['status']}"
    )
    assert job["session_id"] == session_id, (
        f"Job session_id mismatch: {job['session_id']!r} != {session_id!r}"
    )
    assert job["job_id"] == job_id, "job_id must match"
    assert job["started_at"] is None, "started_at must be None for PENDING job"
    assert job["completed_at"] is None, "completed_at must be None for PENDING job"
    assert job["assignments"] == [], "assignments must be empty for PENDING job"
    assert job["error_message"] is None, "error_message must be None for PENDING job"

    # ── RUNNING ───────────────────────────────────────────────────────────────
    # update_job_running() now accepts db directly — no SessionLocal call.
    db2_for_running = factory()
    SolverJobStore.update_job_running(db2_for_running, job_id)
    db2_for_running.commit()  # caller owns the commit (Unit of Work)
    db2_for_running.close()

    # Open a fresh session to read the committed state (bypasses ORM cache).
    db2 = factory()
    try:
        job_running = SolverJobStore.get_job(db2, job_id)
        assert job_running["status"] == JobStatus.RUNNING, (
            f"After update_job_running, status must be RUNNING, got {job_running['status']}"
        )
        assert job_running["started_at"] is not None, (
            "started_at must be set after update_job_running()"
        )
    finally:
        db2.close()

    # ── COMPLETED ─────────────────────────────────────────────────────────────
    fake_assignments = [
        {
            "worker_name": "Alice",
            "shift_name": "Monday Kitchen",
            "score": 5.0,
            "task": "kitchen_task",
            "time": "2024-01-01T08:00:00",
            "role_details": "Chef",
            "score_breakdown": "base=5",
        }
    ]
    fake_violations = {"max_hours": ["Alice exceeded limit"]}

    db3_for_complete = factory()
    SolverJobStore.update_job_completed(
        db=db3_for_complete,
        job_id=job_id,
        result_status="Optimal",
        objective_value=42.0,
        assignments=fake_assignments,
        violations=fake_violations,
        theoretical_max_score=100.0,
    )
    db3_for_complete.commit()  # caller owns the commit (Unit of Work)
    db3_for_complete.close()

    db3 = factory()
    try:
        job_completed = SolverJobStore.get_job(db3, job_id)

        assert job_completed["status"] == JobStatus.COMPLETED, (
            f"After update_job_completed with Optimal, status must be COMPLETED, "
            f"got {job_completed['status']}"
        )
        assert job_completed["result_status"] == "Optimal", (
            f"result_status must be 'Optimal', got {job_completed['result_status']!r}"
        )
        assert job_completed["objective_value"] == pytest.approx(42.0), (
            f"objective_value must be 42.0, got {job_completed['objective_value']!r}"
        )
        assert job_completed["theoretical_max_score"] == pytest.approx(100.0), (
            f"theoretical_max_score must be 100.0, got {job_completed['theoretical_max_score']!r}"
        )
        assert len(job_completed["assignments"]) == 1, (
            f"Expected 1 assignment, got {len(job_completed['assignments'])}"
        )
        assert job_completed["assignments"][0]["worker_name"] == "Alice", (
            f"Assignment worker_name mismatch: {job_completed['assignments'][0]['worker_name']!r}"
        )
        assert job_completed["completed_at"] is not None, (
            "completed_at must be set after update_job_completed()"
        )
    finally:
        db3.close()


def test_job_lifecycle_failed_transition(lifecycle_session, session_id_factory):
    """PENDING → FAILED transition with error_message.

    Verifies that update_job_failed() correctly persists:
    - status = FAILED
    - error_message is the supplied string
    - completed_at is set
    - assignments remains empty (no result data on failure)
    """
    db, factory = lifecycle_session
    session_id = session_id_factory("solver-fail")
    job_id = SolverJobStore.create_job(db, session_id)

    error_msg = "Canonical Week invariant violation: non-canonical dates detected"
    db_for_fail = factory()
    SolverJobStore.update_job_failed(db_for_fail, job_id, error_msg)
    db_for_fail.commit()  # caller owns the commit (Unit of Work)
    db_for_fail.close()

    db2 = factory()
    try:
        job_failed = SolverJobStore.get_job(db2, job_id)

        assert job_failed["status"] == JobStatus.FAILED, (
            f"After update_job_failed, status must be FAILED, got {job_failed['status']}"
        )
        assert job_failed["error_message"] == error_msg, (
            f"error_message mismatch: {job_failed['error_message']!r}"
        )
        assert job_failed["completed_at"] is not None, (
            "completed_at must be set on FAILED job"
        )
        assert job_failed["assignments"] == [], (
            f"FAILED job must have empty assignments, got {job_failed['assignments']}"
        )
    finally:
        db2.close()


def test_job_create_is_scoped_to_session(lifecycle_session, session_id_factory):
    """Each job is isolated to its creating session.

    Creates jobs for two different sessions and verifies get_job() returns
    the correct record for each, with no cross-contamination.
    """
    db, factory = lifecycle_session
    session_a = session_id_factory("session-a")
    session_b = session_id_factory("session-b")

    job_a = SolverJobStore.create_job(db, session_a)
    job_b = SolverJobStore.create_job(db, session_b)

    assert job_a != job_b, "Two jobs must have distinct job IDs"

    record_a = SolverJobStore.get_job(db, job_a)
    record_b = SolverJobStore.get_job(db, job_b)

    assert record_a["session_id"] == session_a, (
        f"Job A session_id: expected {session_a!r}, got {record_a['session_id']!r}"
    )
    assert record_b["session_id"] == session_b, (
        f"Job B session_id: expected {session_b!r}, got {record_b['session_id']!r}"
    )
    assert record_a["job_id"] == job_a
    assert record_b["job_id"] == job_b


def test_get_latest_completed_job_returns_most_recent(lifecycle_session, session_id_factory):
    """get_latest_completed_job() returns the most recently completed job.

    Creates two COMPLETED jobs and verifies the later one is returned.
    """
    db, factory = lifecycle_session
    session_id = session_id_factory("latest-job")

    job1 = SolverJobStore.create_job(db, session_id)
    job2 = SolverJobStore.create_job(db, session_id)

    # Complete both jobs — update_job_completed() now accepts db directly.
    db_complete1 = factory()
    SolverJobStore.update_job_completed(
        db=db_complete1,
        job_id=job1,
        result_status="Optimal",
        objective_value=10.0,
        assignments=[],
        violations={},
    )
    db_complete1.commit()  # caller owns the commit (Unit of Work)
    db_complete1.close()

    db_complete2 = factory()
    SolverJobStore.update_job_completed(
        db=db_complete2,
        job_id=job2,
        result_status="Feasible",
        objective_value=8.0,
        assignments=[{"worker_name": "Bob", "shift_name": "Night"}],
        violations={},
    )
    db_complete2.commit()  # caller owns the commit (Unit of Work)
    db_complete2.close()

    db2 = factory()
    try:
        latest = SolverJobStore.get_latest_completed_job(db2, session_id)

        assert latest is not None, "get_latest_completed_job must return a result"
        # job2 was completed after job1 (created later in the same session).
        assert latest["job_id"] == job2, (
            f"Expected the most recently completed job ({job2!r}), "
            f"got {latest['job_id']!r}"
        )
        assert latest["result_status"] == "Feasible", (
            f"Expected result_status='Feasible', got {latest['result_status']!r}"
        )
    finally:
        db2.close()
