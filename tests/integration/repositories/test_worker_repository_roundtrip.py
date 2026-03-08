"""Repository integration tests for worker persistence and hydration."""

from datetime import datetime

import pytest

from domain.worker_model import Worker


pytestmark = [pytest.mark.integration]


def test_worker_roundtrip_preserves_skills_and_attributes(worker_repo, db_session, id_factory):
    worker = Worker(name="Roundtrip Worker", worker_id=id_factory("worker"), wage=25.0, min_hours=5, max_hours=40)
    worker.set_skill_level("chef", 7)
    worker.add_availability(datetime(2026, 1, 20, 8, 0), datetime(2026, 1, 20, 16, 0))
    worker_repo.add(worker)
    db_session.commit()
    db_session.expire_all()

    loaded = worker_repo.get_by_id(worker.worker_id)
    assert loaded is not None
    assert loaded.skills["Chef"] == 7
    assert loaded.wage == 25.0
    assert len(loaded.availability) == 1

