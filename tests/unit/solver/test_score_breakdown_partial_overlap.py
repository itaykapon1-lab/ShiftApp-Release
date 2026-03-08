"""Regression tests for score breakdown with non-exact preference windows."""

import datetime as dt
from typing import Dict, List, Optional

import pytest

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption
from domain.worker_model import Worker
from solver.solver_engine import ShiftSolver
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


class _MockDataManager:
    """Minimal data manager for solver unit tests."""

    def __init__(self, workers: List[Worker], shifts: List[Shift]):
        self._workers = {w.worker_id: w for w in workers}
        self._shifts = {s.shift_id: s for s in shifts}

    def get_eligible_workers(
        self,
        time_window: TimeWindow,
        required_skills: Optional[Dict[str, int]] = None,
    ) -> List[Worker]:
        required_skills = required_skills or {}
        eligible = []

        for worker in self._workers.values():
            if not worker.is_available_for_shift(time_window):
                continue

            if all(worker.has_skill_at_level(skill, level) for skill, level in required_skills.items()):
                eligible.append(worker)

        return eligible

    def get_all_shifts(self) -> List[Shift]:
        return list(self._shifts.values())

    def get_all_workers(self) -> List[Worker]:
        return list(self._workers.values())

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        return self._workers.get(worker_id)

    def get_shift(self, shift_id: str) -> Optional[Shift]:
        return self._shifts.get(shift_id)

    def refresh_indices(self) -> None:
        pass


def _build_single_shift(shift_window: TimeWindow) -> Shift:
    shift = Shift(name="Morning Shift", time_window=shift_window, shift_id="S1")
    task = Task(name="Kitchen", task_id="T1")
    option = TaskOption()
    option.add_requirement(count=1, required_skills={"Cook": 3})
    task.add_option(option)
    shift.add_task(task)
    return shift


def test_score_breakdown_uses_containment_for_positive_preference():
    base = dt.datetime(2024, 1, 1, 8, 0)
    shift_window = TimeWindow(base, base.replace(hour=16))

    worker = Worker(name="Alice", worker_id="W1")
    worker.set_skill_level("Cook", 5)

    # Non-exact window: still contains the full shift.
    preference_window = TimeWindow(base.replace(hour=7), base.replace(hour=17))
    worker.add_availability(preference_window.start, preference_window.end)
    worker.add_preference(preference_window, 10)

    solver = ShiftSolver(_MockDataManager([worker], [_build_single_shift(shift_window)]))
    result = solver.solve()

    assert result["status"] in ["Optimal", "Feasible"]
    assert result["objective_value"] >= 10
    assert result["assignments"], "Expected at least one assignment"

    assignment = result["assignments"][0]
    assert assignment["score"] == 10
    assert "+10 (Pref)" in assignment["score_breakdown"]


def test_score_breakdown_uses_containment_for_negative_preference():
    base = dt.datetime(2024, 1, 1, 8, 0)
    shift_window = TimeWindow(base, base.replace(hour=16))

    worker = Worker(name="Bob", worker_id="W2")
    worker.set_skill_level("Cook", 5)

    # Non-exact window: still contains the full shift.
    preference_window = TimeWindow(base.replace(hour=7), base.replace(hour=17))
    worker.add_availability(preference_window.start, preference_window.end)
    worker.add_preference(preference_window, -100)

    solver = ShiftSolver(_MockDataManager([worker], [_build_single_shift(shift_window)]))
    result = solver.solve()

    assert result["status"] in ["Optimal", "Feasible"]
    assert result["objective_value"] < 0
    assert result["assignments"], "Expected at least one assignment"

    assignment = result["assignments"][0]
    assert assignment["score"] == -100
    assert "-100 (Avoid)" in assignment["score_breakdown"]
