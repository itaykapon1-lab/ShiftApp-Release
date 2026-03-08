"""Unit tests for configurable worker preference reward/penalty weights."""

import datetime as dt

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.worker_model import Worker
from solver.constraints.base import SolverContext
from solver.constraints.static_soft import WorkerPreferencesConstraint
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


def _build_context(high_score: int = 10, low_score: int = -100):
    """Create a minimal solver context with one worker and two preference-tagged shifts."""
    solver = pywraplp.Solver("worker_pref_weights", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)
    objective = solver.Objective()
    objective.SetMaximization()

    worker = Worker(name="Alice", worker_id="W1")
    base = dt.datetime(2026, 1, 5, 8, 0)

    high_window = TimeWindow(base, base.replace(hour=16))
    low_base = base + dt.timedelta(days=1)
    low_window = TimeWindow(low_base.replace(hour=16), low_base.replace(hour=23))

    worker.add_preference(high_window, high_score)
    worker.add_preference(low_window, low_score)

    high_shift = Shift(name="High pref shift", shift_id="S_HIGH", time_window=high_window)
    low_shift = Shift(name="Low pref shift", shift_id="S_LOW", time_window=low_window)

    x_high = solver.NumVar(0.0, 1.0, "x_high")
    x_low = solver.NumVar(0.0, 1.0, "x_low")

    # Fix both assignments to 1 so objective value equals the sum of applied coefficients.
    solver.Add(x_high == 1.0)
    solver.Add(x_low == 1.0)

    context = SolverContext(
        solver=solver,
        x_vars={
            (worker.worker_id, high_shift.shift_id, "T1", "R"): x_high,
            (worker.worker_id, low_shift.shift_id, "T1", "R"): x_low,
        },
        y_vars={},
        shifts=[high_shift, low_shift],
        workers=[worker],
        worker_shift_assignments={},
        worker_global_assignments={},
        task_metadata={},
    )

    return solver, context, x_high, x_low


def test_worker_preferences_constraint_applies_custom_reward_and_penalty_coefficients():
    solver, context, x_high, x_low = _build_context(high_score=10, low_score=-100)

    constraint = WorkerPreferencesConstraint(preference_reward=50, preference_penalty=-200)
    constraint.apply(context)

    objective = solver.Objective()
    assert objective.GetCoefficient(x_high) == pytest.approx(50)
    assert objective.GetCoefficient(x_low) == pytest.approx(-200)

    status = solver.Solve()
    assert status == pywraplp.Solver.OPTIMAL
    assert objective.Value() == pytest.approx(-150)


def test_worker_preferences_constraint_defaults_preserve_legacy_objective_score():
    solver, context, x_high, x_low = _build_context(high_score=10, low_score=-100)

    constraint = WorkerPreferencesConstraint()
    constraint.apply(context)

    objective = solver.Objective()
    assert objective.GetCoefficient(x_high) == pytest.approx(10)
    assert objective.GetCoefficient(x_low) == pytest.approx(-100)

    status = solver.Solve()
    assert status == pywraplp.Solver.OPTIMAL
    assert objective.Value() == pytest.approx(-90)
