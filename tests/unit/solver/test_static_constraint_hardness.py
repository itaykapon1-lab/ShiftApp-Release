"""Unit tests for HARD/SOFT static constraint strictness behavior."""

from datetime import datetime, timedelta

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.worker_model import Worker
from solver.constraints.base import ConstraintType, SolverContext
from solver.constraints.config import ConstraintConfig
from solver.constraints.definitions import constraint_definitions, register_core_constraints
from solver.constraints.static_soft import (
    AvoidConsecutiveShiftsConstraint,
    MaxHoursPerWeekConstraint,
)
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


def _build_two_shift_context(
    *,
    rest_gap_hours: float,
    fixed_assignments: tuple[int, int] | None = None,
    reward_per_assignment: float = 0.0,
) -> tuple[SolverContext, tuple[Shift, Shift], tuple[pywraplp.Variable, pywraplp.Variable]]:
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None

    worker = Worker(name="Alice", worker_id="W1")

    shift_a_start = datetime(2026, 2, 16, 8, 0, 0)
    shift_a_end = shift_a_start + timedelta(hours=8)
    shift_b_start = shift_a_end + timedelta(hours=rest_gap_hours)
    shift_b_end = shift_b_start + timedelta(hours=8)

    shift_a = Shift(
        shift_id="S1",
        name="Morning",
        time_window=TimeWindow(start=shift_a_start, end=shift_a_end),
    )
    shift_b = Shift(
        shift_id="S2",
        name="Evening",
        time_window=TimeWindow(start=shift_b_start, end=shift_b_end),
    )

    var_a = solver.IntVar(0, 1, "X_W1_S1")
    var_b = solver.IntVar(0, 1, "X_W1_S2")

    if fixed_assignments is not None:
        solver.Add(var_a == fixed_assignments[0])
        solver.Add(var_b == fixed_assignments[1])

    if reward_per_assignment:
        solver.Objective().SetCoefficient(var_a, reward_per_assignment)
        solver.Objective().SetCoefficient(var_b, reward_per_assignment)

    context = SolverContext(
        solver=solver,
        x_vars={
            ("W1", "S1", "T1", ()): var_a,
            ("W1", "S2", "T2", ()): var_b,
        },
        y_vars={},
        shifts=[shift_a, shift_b],
        workers=[worker],
        worker_shift_assignments={
            ("W1", "S1"): [var_a],
            ("W1", "S2"): [var_b],
        },
        worker_global_assignments={
            "W1": [(shift_a, var_a), (shift_b, var_b)],
        },
        task_metadata={},
    )
    return context, (shift_a, shift_b), (var_a, var_b)


def _solve(context: SolverContext) -> int:
    context.solver.Objective().SetMaximization()
    return context.solver.Solve()


def test_max_hours_soft_forced_overage_keeps_optimal_and_applies_exact_penalty():
    context, _, _ = _build_two_shift_context(rest_gap_hours=4, fixed_assignments=(1, 1))
    constraint = MaxHoursPerWeekConstraint(
        max_hours=8,
        penalty_per_hour=-7.5,
        strictness=ConstraintType.SOFT,
    )

    constraint.apply(context)
    status = _solve(context)

    assert status == pywraplp.Solver.OPTIMAL
    assert constraint._slack_vars["W1"].solution_value() == pytest.approx(8.0)
    assert context.solver.Objective().Value() == pytest.approx(-60.0)

    violations = constraint.get_violations(context)
    assert len(violations) == 1
    assert violations[0].penalty == pytest.approx(-60.0)


def test_max_hours_hard_limits_assignments_when_solver_prefers_overtime():
    context, shifts, vars_ = _build_two_shift_context(rest_gap_hours=4, reward_per_assignment=100.0)
    constraint = MaxHoursPerWeekConstraint(
        max_hours=8,
        penalty_per_hour=-1.0,
        strictness=ConstraintType.HARD,
    )

    constraint.apply(context)
    status = _solve(context)

    assert status == pywraplp.Solver.OPTIMAL
    assigned_hours = sum(
        shift.time_window.duration_hours * var.solution_value()
        for shift, var in zip(shifts, vars_)
    )
    assert assigned_hours <= 8.0 + 1e-6


def test_max_hours_hard_forced_overage_becomes_infeasible():
    context, _, _ = _build_two_shift_context(rest_gap_hours=4, fixed_assignments=(1, 1))
    constraint = MaxHoursPerWeekConstraint(
        max_hours=8,
        penalty_per_hour=-1.0,
        strictness=ConstraintType.HARD,
    )

    constraint.apply(context)
    status = _solve(context)
    assert status == pywraplp.Solver.INFEASIBLE


def test_avoid_consecutive_soft_allows_back_to_back_and_applies_penalty():
    context, _, (var_a, var_b) = _build_two_shift_context(rest_gap_hours=1, fixed_assignments=(1, 1))
    constraint = AvoidConsecutiveShiftsConstraint(
        min_rest_hours=12,
        penalty=-25.0,
        strictness=ConstraintType.SOFT,
    )

    constraint.apply(context)
    status = _solve(context)

    assert status == pywraplp.Solver.OPTIMAL
    assert var_a.solution_value() == pytest.approx(1.0)
    assert var_b.solution_value() == pytest.approx(1.0)
    assert context.solver.Objective().Value() == pytest.approx(-25.0)

    violations = constraint.get_violations(context)
    assert len(violations) == 1
    assert violations[0].penalty == pytest.approx(-25.0)


def test_avoid_consecutive_hard_prevents_assigning_both_consecutive_shifts():
    context, _, (var_a, var_b) = _build_two_shift_context(rest_gap_hours=1, reward_per_assignment=100.0)
    constraint = AvoidConsecutiveShiftsConstraint(
        min_rest_hours=12,
        penalty=-25.0,
        strictness=ConstraintType.HARD,
    )

    constraint.apply(context)
    status = _solve(context)

    assert status == pywraplp.Solver.OPTIMAL
    assert var_a.solution_value() + var_b.solution_value() <= 1.0 + 1e-6


def test_avoid_consecutive_hard_forced_back_to_back_is_infeasible():
    context, _, _ = _build_two_shift_context(rest_gap_hours=1, fixed_assignments=(1, 1))
    constraint = AvoidConsecutiveShiftsConstraint(
        min_rest_hours=12,
        penalty=-25.0,
        strictness=ConstraintType.HARD,
    )

    constraint.apply(context)
    status = _solve(context)
    assert status == pywraplp.Solver.INFEASIBLE


def test_hard_static_constraints_report_no_violations():
    max_context, _, _ = _build_two_shift_context(rest_gap_hours=4, reward_per_assignment=100.0)
    max_constraint = MaxHoursPerWeekConstraint(
        max_hours=8,
        penalty_per_hour=-1.0,
        strictness=ConstraintType.HARD,
    )
    max_constraint.apply(max_context)
    assert _solve(max_context) == pywraplp.Solver.OPTIMAL
    assert max_constraint.get_violations(max_context) == []

    rest_context, _, _ = _build_two_shift_context(rest_gap_hours=1, reward_per_assignment=100.0)
    rest_constraint = AvoidConsecutiveShiftsConstraint(
        min_rest_hours=12,
        penalty=-10.0,
        strictness=ConstraintType.HARD,
    )
    rest_constraint.apply(rest_context)
    assert _solve(rest_context) == pywraplp.Solver.OPTIMAL
    assert rest_constraint.get_violations(rest_context) == []


def test_static_definition_factories_pass_strictness_to_runtime_constraints():
    try:
        register_core_constraints()
    except ValueError:
        pass

    max_defn = constraint_definitions.get("max_hours_per_week")
    max_cfg = max_defn.config_model.model_validate(
        {"max_hours": 32, "penalty": -10.0, "strictness": "HARD"}
    )
    max_constraint = max_defn.factory(max_cfg)
    assert max_constraint.type == ConstraintType.HARD

    rest_defn = constraint_definitions.get("avoid_consecutive_shifts")
    rest_cfg = rest_defn.config_model.model_validate(
        {"min_rest_hours": 12, "penalty": -20.0, "strictness": "SOFT"}
    )
    rest_constraint = rest_defn.factory(rest_cfg)
    assert rest_constraint.type == ConstraintType.SOFT


def test_constraint_config_build_registry_passes_static_strictness():
    registry = ConstraintConfig(
        max_hours_per_week=40,
        max_hours_penalty=-10.0,
        max_hours_strictness=ConstraintType.HARD,
        min_rest_hours=12,
        min_rest_penalty=-20.0,
        min_rest_strictness=ConstraintType.HARD,
    ).build_registry()

    by_name = {constraint.name: constraint for constraint in registry._constraints}
    assert by_name["max_hours_per_week"].type == ConstraintType.HARD
    assert by_name["avoid_consecutive_shifts"].type == ConstraintType.HARD
