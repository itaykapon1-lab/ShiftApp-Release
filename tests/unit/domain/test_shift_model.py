"""Unit tests for Shift domain behavior."""

from datetime import datetime

import pytest

from domain.shift_model import Shift
from domain.task_model import Task
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


def test_shift_add_task():
    shift = Shift(name="Morning", shift_id="S1", time_window=TimeWindow(datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 16)))
    shift.add_task(Task("Kitchen"))
    assert len(shift.tasks) == 1
    assert shift.tasks[0].name == "Kitchen"


def test_shift_equality_uses_shift_id():
    a = Shift(name="A", shift_id="SAME", time_window=TimeWindow(datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 16)))
    b = Shift(name="B", shift_id="SAME", time_window=TimeWindow(datetime(2024, 1, 2, 8), datetime(2024, 1, 2, 16)))
    assert a == b

