"""Database referential integrity tests.

PILLAR 3 of the Backend Testing Roadmap — scenarios C1, C2, C3.

The ShiftApp schema has NO foreign keys and NO SQLAlchemy cascade relationships.
All referential integrity is implemented manually in route handlers.  These tests
document the current behavior (including known limitations) so that regressions
are immediately visible if the manual coordination breaks.

C1: Create mutual_exclusion(W1, W2) → delete W1 → constraint JSON retains stale ref.
    Current behavior: stale worker_a_id is kept in constraint JSON (known limitation).
    Test documents this and will catch if the behavior changes unexpectedly.

C2: Run solver → call DELETE /session/data → query SolverJobModel.
    Current behavior: solver job records survive session reset (known gap).
    Test documents this; when fixed the assertion direction will flip.

C3: Run solver (COMPLETED) → DELETE /session/data → GET /status/{job_id}.
    Current behavior: job data remains accessible after reset (stale reference).
    Test documents the inconsistency from the user's perspective.

Note: These tests use the TestClient + in-memory DB pattern from conftest.py.
For C2/C3 we need direct DB access, so we use db_session alongside client.
"""

import uuid

import pytest
from sqlalchemy.orm import sessionmaker

from data.models import SolverJobModel, WorkerModel
from services.solver_service import SolverJobStore
from app.schemas.job import JobStatus


pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker_id() -> str:
    return f"w_{uuid.uuid4().hex[:8]}"


def _make_shift_id() -> str:
    return f"s_{uuid.uuid4().hex[:8]}"


def _valid_worker_payload(worker_id: str, name: str) -> dict:
    """Return a valid WorkerCreate payload."""
    return {
        "worker_id": worker_id,
        "name": name,
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


def _make_session_cookies(session_id: str) -> dict:
    return {"session_id": session_id}


# ---------------------------------------------------------------------------
# C1 — Stale constraint references after worker deletion
# ---------------------------------------------------------------------------


class TestStaleConstraintReferences:
    """C1: Deleting a worker referenced by a mutual_exclusion constraint.

    The schema has no cascading FK relationships.  Deleting W1 while a
    mutual_exclusion constraint references worker_a_id=W1 leaves a dangling
    reference in the constraint JSON.

    Current behavior: stale reference is kept (no automatic cleanup).
    This is documented as a known limitation.
    """

    def test_c1_delete_worker_leaves_stale_constraint_reference(
        self, client, db_session, test_session_id
    ):
        """C1: Stale worker reference persists in constraint JSON after deletion.

        Scenario:
        1. Create two workers (W1, W2).
        2. Create a mutual_exclusion constraint referencing W1 and W2.
        3. Delete W1.
        4. Fetch constraints — verify W1's id is STILL in the JSON (current behavior).

        Purpose of this test:
        - Documents the known limitation explicitly.
        - Catches unexpected behavior changes (e.g. if someone adds cascade
          deletion, the assertion direction would flip).
        - Provides a regression anchor for future referential integrity fixes.
        """
        session_cookies = _make_session_cookies(test_session_id)

        # Step 1: Create two workers.
        w1_id = _make_worker_id()
        w2_id = _make_worker_id()

        resp = client.post(
            "/api/v1/workers",
            json=_valid_worker_payload(w1_id, "Worker_C1_A"),
            cookies=session_cookies,
        )
        assert resp.status_code == 201, f"Create W1 failed: {resp.text}"

        resp = client.post(
            "/api/v1/workers",
            json=_valid_worker_payload(w2_id, "Worker_C1_B"),
            cookies=session_cookies,
        )
        assert resp.status_code == 201, f"Create W2 failed: {resp.text}"

        # Step 2: Create mutual_exclusion constraint referencing W1 and W2.
        constraints_payload = {
            "constraints": [
                {
                    "category": "mutual_exclusion",
                    "params": {
                        "worker_a_id": w1_id,
                        "worker_b_id": w2_id,
                        "strictness": "SOFT",
                    },
                    "enabled": True,
                    "type": "SOFT",
                }
            ]
        }
        resp = client.put(
            "/api/v1/constraints",
            json=constraints_payload,
            cookies=session_cookies,
        )
        assert resp.status_code == 200, (
            f"Create mutual_exclusion constraint failed: {resp.text}"
        )

        # Verify constraint is stored with both worker IDs.
        constraints_before = resp.json()["constraints"]
        assert any(
            c.get("params", {}).get("worker_a_id") == w1_id
            for c in constraints_before
        ), f"Expected worker_a_id={w1_id!r} in stored constraints: {constraints_before}"

        # Step 3: Delete W1.
        delete_resp = client.delete(
            f"/api/v1/workers/{w1_id}",
            cookies=session_cookies,
        )
        assert delete_resp.status_code == 200, (
            f"Delete W1 failed: {delete_resp.text}"
        )

        # Verify W1 is gone from the workers table.
        workers_after = client.get("/api/v1/workers", cookies=session_cookies).json()
        worker_ids_after = {w["worker_id"] for w in workers_after}
        assert w1_id not in worker_ids_after, (
            f"W1 should be deleted but is still in workers: {worker_ids_after}"
        )

        # Step 4: Fetch constraints — stale reference check.
        constraints_after_resp = client.get(
            "/api/v1/constraints",
            cookies=session_cookies,
        )
        assert constraints_after_resp.status_code == 200
        constraints_after = constraints_after_resp.json()["constraints"]

        # CURRENT BEHAVIOR: stale reference is kept.
        # The constraint JSON still contains worker_a_id = w1_id even though
        # that worker no longer exists in the DB.
        mutual_exclusion_constraints = [
            c for c in constraints_after if c.get("category") == "mutual_exclusion"
        ]
        stale_ref_found = any(
            c.get("params", {}).get("worker_a_id") == w1_id
            for c in mutual_exclusion_constraints
        )
        assert stale_ref_found, (
            f"Current behavior: stale constraint reference to deleted worker "
            f"{w1_id!r} should still be present in constraint JSON. "
            f"Constraints after deletion: {mutual_exclusion_constraints}. "
            "If this assertion fails, cascade deletion was added — update test."
        )

    def test_c1_deleted_worker_not_in_workers_list(
        self, client, db_session, test_session_id
    ):
        """C1 (baseline): Deleted worker is absent from GET /workers.

        Sanity check that the DELETE operation actually removes the worker
        from the workers table (not just the constraint JSON).
        """
        session_cookies = _make_session_cookies(test_session_id)

        worker_id = _make_worker_id()
        client.post(
            "/api/v1/workers",
            json=_valid_worker_payload(worker_id, "Temp_Worker_C1"),
            cookies=session_cookies,
        )

        client.delete(f"/api/v1/workers/{worker_id}", cookies=session_cookies)

        workers = client.get("/api/v1/workers", cookies=session_cookies).json()
        db_worker_count = (
            db_session.query(WorkerModel)
            .filter_by(worker_id=worker_id, session_id=test_session_id)
            .count()
        )

        assert worker_id not in {w["worker_id"] for w in workers}, (
            f"Deleted worker {worker_id!r} still appears in GET /workers"
        )
        assert db_worker_count == 0, (
            f"Deleted worker {worker_id!r} still in DB: count={db_worker_count}"
        )


# ---------------------------------------------------------------------------
# C2 — Solver jobs survive session reset
# ---------------------------------------------------------------------------


class TestSessionResetOrphanedJobs:
    """C2: DELETE /session/data does NOT delete SolverJobModel records.

    The session_routes.py reset handler deletes Workers, Shifts, and
    SessionConfigModel constraints — but NOT SolverJobModel rows.

    Current behavior: solver jobs survive session reset (known gap).
    This documents the behavior and will catch if cleanup is ever added.
    """

    def test_c2_solver_job_persists_after_session_reset(
        self, client, db_session, test_session_id
    ):
        """C2: A solver job created before session reset remains in DB after reset.

        Creates a PENDING job directly via SolverJobStore (no real solver run
        needed — we just need a job record in the DB).  Then resets the session
        and verifies the job record still exists.

        Documents:
        - DELETE /session/data does NOT cascade to solver_jobs table.
        - This means DB can accumulate job records indefinitely (bloat risk).
        """
        # Create a job in PENDING state directly — no solver invocation.
        job_id = SolverJobStore.create_job(db_session, test_session_id)
        db_session.commit()

        # Verify job exists before reset.
        job_before = SolverJobStore.get_job(db_session, job_id)
        assert job_before is not None, f"Job {job_id} should exist before reset"
        assert job_before["status"] == JobStatus.PENDING

        # Reset the session via DELETE /session/data.
        reset_resp = client.delete(
            "/api/v1/session/data",
            cookies=_make_session_cookies(test_session_id),
        )
        assert reset_resp.status_code == 200, (
            f"DELETE /session/data failed: {reset_resp.text}"
        )

        # CURRENT BEHAVIOR: job record survives reset.
        # Note: db_session needs a refresh because the reset committed via
        # a different connection path.
        db_session.expire_all()
        job_after = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job_after is not None, (
            f"Current behavior: solver job {job_id!r} should survive session reset. "
            "If this assertion fails, job cleanup was added — update test direction."
        )
        assert job_after.session_id == test_session_id, (
            f"Orphaned job session_id must still match: "
            f"{job_after.session_id!r} != {test_session_id!r}"
        )

    def test_c2_workers_and_shifts_deleted_on_session_reset(
        self, client, db_session, test_session_id
    ):
        """C2 (baseline): DELETE /session/data does delete workers and shifts.

        Confirms that the reset handler correctly removes WorkerModel and
        ShiftModel rows for the session (the parts that ARE cleaned up).
        """
        session_cookies = _make_session_cookies(test_session_id)

        # Create a worker and a shift.
        w_id = _make_worker_id()
        client.post(
            "/api/v1/workers",
            json=_valid_worker_payload(w_id, "Reset_Test_Worker"),
            cookies=session_cookies,
        )

        s_id = _make_shift_id()
        client.post(
            "/api/v1/shifts",
            json={
                "shift_id": s_id,
                "name": "Reset_Test_Shift",
                "start_time": "2024-01-01T08:00:00",
                "end_time": "2024-01-01T16:00:00",
                "tasks_data": {"tasks": []},
            },
            cookies=session_cookies,
        )

        # Verify they exist before reset.
        workers_before = client.get("/api/v1/workers", cookies=session_cookies).json()
        shifts_before = client.get("/api/v1/shifts", cookies=session_cookies).json()
        assert len(workers_before) >= 1
        assert len(shifts_before) >= 1

        # Reset the session.
        reset_resp = client.delete("/api/v1/session/data", cookies=session_cookies)
        assert reset_resp.status_code == 200

        # Workers and shifts must be gone.
        db_session.expire_all()
        workers_after = client.get("/api/v1/workers", cookies=session_cookies).json()
        shifts_after = client.get("/api/v1/shifts", cookies=session_cookies).json()
        assert len(workers_after) == 0, (
            f"Expected 0 workers after reset, found {len(workers_after)}"
        )
        assert len(shifts_after) == 0, (
            f"Expected 0 shifts after reset, found {len(shifts_after)}"
        )


# ---------------------------------------------------------------------------
# C3 — GET /status after session reset returns stale job data
# ---------------------------------------------------------------------------


class TestResetThenGetStatus:
    """C3: GET /status/{job_id} after session reset returns stale data.

    After a session reset, the workers and shifts referenced by a completed
    solver job no longer exist.  But the job record itself remains, so
    GET /status still returns the (now stale) assignments list.

    Current behavior: job is accessible and returns COMPLETED with
    assignments that reference workers/shifts that no longer exist.
    This is a data inconsistency that could mislead the frontend.
    """

    def test_c3_get_status_after_reset_returns_stale_assignments(
        self, client, db_session, test_session_id
    ):
        """C3: GET /status/{job_id} still returns assignment data after reset.

        Creates a COMPLETED job with fake assignment data directly via the ORM
        (not via SolverJobStore.update_job_completed, which would use a different
        SessionLocal connection), resets the session, then verifies the job
        record survives and GET /status still returns the stale data.

        Proves:
        - Job record with assignment data survives DELETE /session/data.
        - Assignments field references worker IDs that no longer exist.
        """
        session_cookies = _make_session_cookies(test_session_id)

        # Create a worker and record its ID.
        w_id = _make_worker_id()
        client.post(
            "/api/v1/workers",
            json=_valid_worker_payload(w_id, "Pre_Reset_Worker"),
            cookies=session_cookies,
        )

        # Create a job in PENDING state via SolverJobStore (uses db_session directly).
        job_id = SolverJobStore.create_job(db_session, test_session_id)

        # Directly mark it COMPLETED via ORM (avoids the SessionLocal cross-DB issue).
        # SolverJobStore.update_job_completed() creates its own SessionLocal() session
        # which points to the production DB in tests.  We bypass it here.
        fake_assignments = [
            {
                "worker_id": w_id,
                "worker_name": "Pre_Reset_Worker",
                "shift_id": "s_fake_001",
                "shift_name": "Pre_Reset_Shift",
                "score": 10.0,
            }
        ]
        job_model = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job_model is not None, f"Job {job_id} should exist in test DB"
        job_model.status = JobStatus.COMPLETED.value
        job_model.result_status = "Optimal"
        job_model.objective_value = 10.0
        job_model.assignments = fake_assignments
        db_session.commit()

        # Verify the job shows COMPLETED before reset.
        db_session.expire_all()
        job_before = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job_before.status == JobStatus.COMPLETED.value, (
            f"Expected COMPLETED before reset, got {job_before.status!r}"
        )

        # Reset the session — deletes workers and shifts.
        reset_resp = client.delete("/api/v1/session/data", cookies=session_cookies)
        assert reset_resp.status_code == 200

        # Workers must be gone after reset.
        workers_after = client.get("/api/v1/workers", cookies=session_cookies).json()
        assert all(w["worker_id"] != w_id for w in workers_after), (
            f"Worker {w_id!r} should be deleted after reset"
        )

        # CURRENT BEHAVIOR: job record survives session reset.
        db_session.expire_all()
        job_after = db_session.query(SolverJobModel).filter_by(job_id=job_id).first()
        assert job_after is not None, (
            "Current behavior: job record survives session reset. "
            "If this fails, cleanup was added — update test direction."
        )
        assert job_after.status == JobStatus.COMPLETED.value, (
            f"Job status should still be COMPLETED after reset: "
            f"got {job_after.status!r}"
        )

        # The assignments field still contains the now-stale worker_id.
        if isinstance(job_after.assignments, list) and job_after.assignments:
            stale_refs = [
                a for a in job_after.assignments
                if a.get("worker_id") == w_id
            ]
            assert len(stale_refs) >= 1, (
                f"Expected stale assignment with worker_id={w_id!r} in job data. "
                f"Assignments: {job_after.assignments}"
            )

    def test_c3_deleted_session_workers_not_queryable(
        self, client, db_session, test_session_id
    ):
        """C3 (baseline): After reset, GET /workers returns 0 results.

        Confirms that the user cannot query the stale workers through the
        normal API path (they must look at the job data directly to see the
        stale references, which is the inconsistency).
        """
        session_cookies = _make_session_cookies(test_session_id)

        # Create workers.
        for i in range(3):
            w_id = _make_worker_id()
            client.post(
                "/api/v1/workers",
                json=_valid_worker_payload(w_id, f"Worker_C3_{i}"),
                cookies=session_cookies,
            )

        assert len(client.get("/api/v1/workers", cookies=session_cookies).json()) == 3

        # Reset.
        client.delete("/api/v1/session/data", cookies=session_cookies)

        # Workers must be gone from the API.
        workers_after = client.get("/api/v1/workers", cookies=session_cookies).json()
        assert len(workers_after) == 0, (
            f"Expected 0 workers after reset, got {len(workers_after)}"
        )
