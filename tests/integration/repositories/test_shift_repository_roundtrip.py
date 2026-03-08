"""Repository integration tests for shift persistence and task hydration."""

from datetime import datetime

import pytest

from app.utils.date_normalization import normalize_to_canonical_week
from domain.shift_model import Shift
from domain.task_model import Task, TaskOption
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.integration]


def test_shift_roundtrip_hydrates_tasks_and_canonical_dates(shift_repo, db_session, id_factory):
    shift = Shift(
        name="Roundtrip Shift",
        shift_id=id_factory("shift"),
        time_window=TimeWindow(datetime(2026, 1, 22, 10, 0), datetime(2026, 1, 22, 18, 0)),
    )
    task = Task(name="Bar Service")
    option = TaskOption(preference_score=5)
    option.add_requirement(count=1, required_skills={"Bartender": 3})
    task.add_option(option)
    shift.add_task(task)

    shift_repo.add(shift)
    db_session.commit()
    db_session.expire_all()

    loaded = shift_repo.get_by_id(shift.shift_id)
    assert loaded is not None
    assert loaded.time_window.start == normalize_to_canonical_week(datetime(2026, 1, 22, 10, 0))
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].options[0].requirements[0].required_skills["Bartender"] == 3

