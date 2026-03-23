"""Determinism / Seed Test: verify the solver is seeded for reproducibility.

TDD anchor for the upcoming solver seed safeguard.
When the ShiftSolver creates an OR-Tools solver instance, it must explicitly
set a deterministic seed (e.g., 42) via one of these OR-Tools mechanisms:

  - solver.SetSolverSpecificParametersAsString(...)  with a seed parameter
  - cp_model.parameters.random_seed = 42  (if migrating to CP-SAT)

This ensures identical inputs produce identical schedules across runs.

These tests will FAIL until the seeding logic is implemented.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock, call

import pytest

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_trivial_data_manager():
    """Return a stub data manager with minimal solvable input."""
    tw = TimeWindow(start=datetime(2024, 1, 1, 8, 0), end=datetime(2024, 1, 1, 16, 0))

    worker = Worker(
        worker_id="W1", name="Alice", skills={"Cook": 5}, availability=[tw],
    )
    option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
    task = Task(task_id="T1", name="Kitchen", options=[option])
    shift = Shift(shift_id="S1", name="Morning", time_window=tw, tasks=[task])

    class _DM:
        def get_all_shifts(self):
            return [shift]

        def get_all_workers(self):
            return [worker]

        def get_worker(self, wid):
            return worker if wid == "W1" else None

        def get_shift(self, sid):
            return shift if sid == "S1" else None

        def get_eligible_workers(self, time_window, required_skills):
            return [worker]

        def refresh_indices(self):
            pass

        def get_statistics(self):
            return {"workers": 1, "shifts": 1}

    return _DM()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSolverDeterminism:
    """The solver must set an explicit random seed for reproducibility."""

    def test_solver_sets_seed_via_parameters_string(self):
        """Verify SetSolverSpecificParametersAsString is called with a seed value."""
        dm = _build_trivial_data_manager()

        from solver.solver_engine import ShiftSolver

        solver_instance = ShiftSolver(data_manager=dm)

        # Patch the OR-Tools solver creation to capture the parameters call
        real_create = None
        seed_calls = []

        from ortools.linear_solver import pywraplp

        original_create = pywraplp.Solver.CreateSolver

        def _tracking_create(solver_id):
            s = original_create(solver_id)
            if s is not None:
                original_set_params = s.SetSolverSpecificParametersAsString

                def _capture_params(params_str):
                    seed_calls.append(params_str)
                    return original_set_params(params_str)

                s.SetSolverSpecificParametersAsString = _capture_params
            return s

        with patch.object(pywraplp.Solver, "CreateSolver", side_effect=_tracking_create):
            solver_instance2 = ShiftSolver(data_manager=dm)
            solver_instance2.solve()

        # At least one call should contain a seed parameter
        all_params = " ".join(seed_calls).lower()
        assert any(
            keyword in all_params
            for keyword in ["seed", "randomseed", "random_seed", "randomseedshift"]
        ), (
            f"Expected solver to set a random seed via SetSolverSpecificParametersAsString, "
            f"but captured calls were: {seed_calls}"
        )

    def test_same_input_produces_same_output(self):
        """Two identical solves must produce the same assignments."""
        dm = _build_trivial_data_manager()

        from solver.solver_engine import ShiftSolver

        results = []
        for _ in range(3):
            solver = ShiftSolver(data_manager=dm)
            result = solver.solve()
            results.append(result)

        # All assignment lists should be identical
        first_assignments = results[0].get("assignments", [])
        for i, r in enumerate(results[1:], start=2):
            assert r.get("assignments", []) == first_assignments, (
                f"Run {i} produced different assignments. "
                f"Expected: {first_assignments}, Got: {r.get('assignments', [])}"
            )

        # All objective values should be identical
        first_obj = results[0].get("objective_value", 0)
        for i, r in enumerate(results[1:], start=2):
            assert r.get("objective_value", 0) == first_obj, (
                f"Run {i} produced different objective value."
            )
