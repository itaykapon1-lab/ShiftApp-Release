"""Circuit Breaker: reject inputs that would produce an intractable MILP model.

TDD anchor for the upcoming MAX_SOLVER_VARIABLES safeguard.
The solver pipeline must raise a clear ValueError BEFORE building the
mathematical model when the combinatorial explosion of
(shifts * tasks * eligible_workers) exceeds the safety threshold.

Expected constant: MAX_SOLVER_VARIABLES = 50_000
Expected location: solver/solver_engine.py (or app/core/constants.py)

These tests will FAIL until the circuit breaker is implemented.
"""

from datetime import datetime, timedelta
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker
from repositories.interfaces import IDataManager


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_time_window(day_offset: int, start_hour: int = 8, duration_hours: int = 8) -> TimeWindow:
    """Create a TimeWindow anchored to the canonical epoch week."""
    base = datetime(2024, 1, 1) + timedelta(days=day_offset)
    return TimeWindow(
        start=base.replace(hour=start_hour, minute=0),
        end=base.replace(hour=start_hour + duration_hours, minute=0),
    )


def _build_massive_scenario(
    n_shifts: int = 100,
    n_tasks_per_shift: int = 10,
    n_workers: int = 50,
) -> tuple[list[Shift], list[Worker]]:
    """Build a scenario that exceeds MAX_SOLVER_VARIABLES.

    Each task has 1 option requiring 1 worker with skill "General".
    Every worker is eligible for every task → total X variables =
    n_shifts * n_tasks * n_workers = 100 * 10 * 50 = 50_000.
    """
    shifts: list[Shift] = []
    for s_idx in range(n_shifts):
        tw = _make_time_window(
            day_offset=s_idx % 7,
            start_hour=8 + (s_idx % 3) * 4,
            duration_hours=4,
        )
        shift = Shift(
            shift_id=f"S_{s_idx:04d}",
            name=f"Shift_{s_idx}",
            time_window=tw,
        )
        for t_idx in range(n_tasks_per_shift):
            option = TaskOption(
                requirements=[Requirement(count=1, required_skills={"General": 1})],
            )
            task = Task(
                task_id=f"T_{s_idx}_{t_idx}",
                name=f"Task_{s_idx}_{t_idx}",
                options=[option],
            )
            shift.add_task(task)
        shifts.append(shift)

    workers: list[Worker] = []
    for w_idx in range(n_workers):
        tw = TimeWindow(
            start=datetime(2024, 1, 1, 0, 0),
            end=datetime(2024, 1, 7, 23, 59),
        )
        worker = Worker(
            worker_id=f"W_{w_idx:04d}",
            name=f"Worker_{w_idx}",
            skills={"General": 5},
            availability=[tw],
        )
        workers.append(worker)

    return shifts, workers


class _StubDataManager:
    """Minimal IDataManager that returns pre-built domain objects."""

    def __init__(self, workers: list[Worker], shifts: list[Shift]):
        self._workers = workers
        self._shifts = shifts

    def get_all_shifts(self) -> list[Shift]:
        return self._shifts

    def get_all_workers(self) -> list[Worker]:
        return self._workers

    def get_worker(self, worker_id: str):
        return next((w for w in self._workers if w.worker_id == worker_id), None)

    def get_shift(self, shift_id: str):
        return next((s for s in self._shifts if s.shift_id == shift_id), None)

    def get_eligible_workers(self, time_window, required_skills) -> list[Worker]:
        """All workers are eligible (worst-case scenario)."""
        return list(self._workers)

    def refresh_indices(self) -> None:
        pass

    def get_statistics(self) -> dict:
        return {"workers": len(self._workers), "shifts": len(self._shifts)}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    """The solver must reject inputs that exceed MAX_SOLVER_VARIABLES."""

    def test_massive_input_raises_before_model_build(self):
        """100 shifts * 10 tasks * 50 workers = 50,000 variables → must raise ValueError."""
        shifts, workers = _build_massive_scenario(
            n_shifts=100, n_tasks_per_shift=10, n_workers=50,
        )
        dm = _StubDataManager(workers, shifts)

        from solver.solver_engine import ShiftSolver

        solver = ShiftSolver(data_manager=dm)

        with pytest.raises(ValueError, match="(?i)max.*variable|variable.*limit|circuit.?breaker"):
            solver.solve()

    def test_just_below_threshold_does_not_raise(self):
        """A scenario with fewer than MAX_SOLVER_VARIABLES should proceed normally."""
        # 5 shifts * 2 tasks * 3 workers = 30 variables — well under any threshold
        shifts, workers = _build_massive_scenario(
            n_shifts=5, n_tasks_per_shift=2, n_workers=3,
        )
        dm = _StubDataManager(workers, shifts)

        from solver.solver_engine import ShiftSolver

        solver = ShiftSolver(data_manager=dm)
        # Should NOT raise — the result may be infeasible but the model builds
        result = solver.solve()
        assert result is not None
        assert "status" in result

    def test_error_message_contains_variable_count(self):
        """The ValueError message should include the estimated variable count."""
        shifts, workers = _build_massive_scenario(
            n_shifts=100, n_tasks_per_shift=10, n_workers=50,
        )
        dm = _StubDataManager(workers, shifts)

        from solver.solver_engine import ShiftSolver

        solver = ShiftSolver(data_manager=dm)

        with pytest.raises(ValueError) as exc_info:
            solver.solve()

        msg = str(exc_info.value).lower()
        # The message should reference the count or the limit
        assert any(
            token in msg
            for token in ["50000", "50,000", "50_000", "variable", "limit", "threshold"]
        ), f"Error message should reference variable count or limit, got: {exc_info.value}"
