"""API contract tests for worker routes.

Sprint 3 hardening: added DB-state assertions after CRUD operations and
field-value verification on returned payloads.
"""

import pytest

from data.models import WorkerModel


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_worker_create_update_delete_contract(client, db_session, id_factory, test_session_id):
    """Full CRUD cycle for a worker with DB-state verification at each step.

    Hardens the original status-code-only test by asserting observable DB state
    after each mutation:
    - CREATE: worker row exists in DB with correct field values.
    - UPDATE: worker row reflects the updated name.
    - DELETE: worker row is absent from the DB (count == 0).
    """
    worker_id = id_factory("worker")
    payload = {
        "worker_id": worker_id,
        "name": "Contract Worker",
        "attributes": {
            "skills": {"Chef": 5},
            "availability": {"MON": {"timeRange": "08:00-16:00", "preference": "NEUTRAL"}},
            "wage": 20,
            "min_hours": 0,
            "max_hours": 40,
        },
    }
    session_cookies = {"session_id": test_session_id}

    # ── CREATE ──────────────────────────────────────────────────────────────
    create = client.post("/api/v1/workers", json=payload, cookies=session_cookies)
    assert create.status_code == 201
    created_body = create.json()
    assert created_body["worker_id"] == worker_id
    # Field-value assertions on returned payload.
    assert created_body["name"] == "Contract Worker", (
        f"Expected name='Contract Worker', got {created_body['name']!r}"
    )
    assert created_body["attributes"]["skills"] == {"Chef": 5}, (
        f"Expected skills={{'Chef': 5}}, got {created_body['attributes'].get('skills')!r}"
    )

    # DB-state: worker row must exist with correct name.
    db_session.expire_all()
    db_worker = db_session.query(WorkerModel).filter_by(
        worker_id=worker_id, session_id=test_session_id
    ).first()
    assert db_worker is not None, (
        f"Worker {worker_id!r} must exist in DB after POST /workers"
    )
    assert db_worker.name == "Contract Worker", (
        f"DB worker name mismatch: {db_worker.name!r}"
    )

    # ── UPDATE ──────────────────────────────────────────────────────────────
    payload["name"] = "Updated Worker"
    update = client.put(
        f"/api/v1/workers/{worker_id}", json=payload, cookies=session_cookies
    )
    assert update.status_code == 200
    updated_body = update.json()
    assert updated_body["name"] == "Updated Worker", (
        f"Expected updated name='Updated Worker', got {updated_body['name']!r}"
    )

    # DB-state: name must be updated in the row.
    db_session.expire_all()
    db_worker_updated = db_session.query(WorkerModel).filter_by(
        worker_id=worker_id
    ).first()
    assert db_worker_updated is not None, "Worker must still exist after PUT"
    assert db_worker_updated.name == "Updated Worker", (
        f"DB worker name not updated: {db_worker_updated.name!r}"
    )

    # ── DELETE ──────────────────────────────────────────────────────────────
    delete = client.delete(f"/api/v1/workers/{worker_id}", cookies=session_cookies)
    assert delete.status_code == 200

    # DB-state: worker row must be ABSENT after DELETE.
    db_session.expire_all()
    db_count_after_delete = db_session.query(WorkerModel).filter_by(
        worker_id=worker_id, session_id=test_session_id
    ).count()
    assert db_count_after_delete == 0, (
        f"Worker {worker_id!r} must be absent from DB after DELETE, "
        f"found {db_count_after_delete} row(s)"
    )


def test_worker_get_returns_only_session_scoped_workers(
    client, db_session, id_factory, test_session_id
):
    """GET /workers returns only workers belonging to the current session.

    Creates 2 workers in the test session and 0 in another.
    Verifies the response contains exactly those 2 workers.
    """
    session_cookies = {"session_id": test_session_id}

    w1_id = id_factory("w1")
    w2_id = id_factory("w2")

    for wid, wname in [(w1_id, "Alpha Worker"), (w2_id, "Beta Worker")]:
        resp = client.post(
            "/api/v1/workers",
            json={
                "worker_id": wid,
                "name": wname,
                "attributes": {
                    "skills": {"Chef": 3},
                    "availability": {},
                    "wage": 15.0,
                    "min_hours": 0,
                    "max_hours": 40,
                },
            },
            cookies=session_cookies,
        )
        assert resp.status_code == 201, f"Create worker {wname!r} failed: {resp.text}"

    workers_resp = client.get("/api/v1/workers", cookies=session_cookies)
    assert workers_resp.status_code == 200
    workers = workers_resp.json()

    # Exactly 2 workers for this session.
    assert len(workers) == 2, (
        f"Expected 2 workers, got {len(workers)}: {[w['name'] for w in workers]}"
    )
    worker_ids = {w["worker_id"] for w in workers}
    assert w1_id in worker_ids, f"Alpha Worker not found in GET /workers: {worker_ids}"
    assert w2_id in worker_ids, f"Beta Worker not found in GET /workers: {worker_ids}"

    # DB-state: exactly 2 rows for this session.
    db_session.expire_all()
    db_count = db_session.query(WorkerModel).filter_by(
        session_id=test_session_id
    ).count()
    assert db_count == 2, (
        f"Expected 2 WorkerModel rows in DB for session, found {db_count}"
    )

