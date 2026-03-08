"""Unit tests for Worker domain behavior."""

from datetime import datetime

import pytest

from domain.worker_model import Worker
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


def test_set_skill_level_bounds():
    worker = Worker(name="Alice", worker_id="W1")
    worker.set_skill_level("chef", 5)
    assert worker.get_skill_level("Chef") == 5
    with pytest.raises(ValueError):
        worker.set_skill_level("Chef", 0)
    with pytest.raises(ValueError):
        worker.set_skill_level("Chef", 11)


def test_is_available_for_shift():
    worker = Worker(name="Bob", worker_id="W2")
    worker.add_availability(datetime(2024, 1, 1, 8, 0), datetime(2024, 1, 1, 16, 0))
    assert worker.is_available_for_shift(TimeWindow(datetime(2024, 1, 1, 9, 0), datetime(2024, 1, 1, 15, 0)))
    assert not worker.is_available_for_shift(TimeWindow(datetime(2024, 1, 1, 7, 0), datetime(2024, 1, 1, 10, 0)))


def test_preference_score_matches_time_of_day_not_date():
    worker = Worker(name="Cara", worker_id="W3")
    pref_window = TimeWindow(datetime(2024, 1, 1, 9, 0), datetime(2024, 1, 1, 17, 0))
    worker.add_preference(pref_window, 10)
    same_time_other_date = TimeWindow(datetime(2024, 1, 4, 9, 0), datetime(2024, 1, 4, 17, 0))
    assert worker.calculate_preference_score(same_time_other_date) == 10

