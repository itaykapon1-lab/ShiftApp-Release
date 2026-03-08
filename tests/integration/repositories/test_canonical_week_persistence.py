"""Repository integration tests for canonical-week persistence invariants."""

from datetime import datetime

import pytest

from app.utils.date_normalization import CANONICAL_ANCHOR_DATES
from domain.shift_model import Shift
from domain.worker_model import Worker
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.integration]


def test_shift_dates_persist_in_canonical_week(shift_repo, db_session, id_factory):
    shift = Shift(
        name="Canonical Shift",
        shift_id=id_factory("shift"),
        time_window=TimeWindow(datetime(2026, 1, 22, 9, 0), datetime(2026, 1, 22, 17, 0)),  # Thursday
    )
    shift_repo.add(shift)
    db_session.commit()
    loaded = shift_repo.get_by_id(shift.shift_id)
    assert loaded.time_window.start.date() == CANONICAL_ANCHOR_DATES[3]
    assert loaded.time_window.end.date() == CANONICAL_ANCHOR_DATES[3]


def test_worker_legacy_availability_hydrates_to_canonical_week(worker_repo, db_session, id_factory):
    """Workers with legacy list-format availability in the DB hydrate to canonical week dates.

    This tests the _to_domain() path: a WorkerModel stored with the old list format
    ({"start": "...", "end": "..."} items) must produce availability windows anchored
    to the canonical epoch, regardless of the real calendar dates in the stored data.
    """
    from data.models import WorkerModel

    # 2026-01-20 is a Tuesday (weekday 1 in Mon=0 indexing)
    model = WorkerModel(
        worker_id=id_factory("worker"),
        name="Legacy",
        session_id=worker_repo.session_id,
        attributes={
            "availability": [
                {"start": "2026-01-20T08:00:00", "end": "2026-01-20T16:00:00"},
            ]
        },
    )
    db_session.add(model)
    db_session.commit()

    loaded = worker_repo.get_by_id(model.worker_id)
    assert len(loaded.availability) == 1
    # Canonical Tuesday = CANONICAL_ANCHOR_DATES[1] = 2024-01-02
    assert loaded.availability[0].start.date() == CANONICAL_ANCHOR_DATES[1]

