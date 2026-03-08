"""Regression guards for HARD/SOFT strictness vulnerabilities."""

from datetime import datetime, timedelta

import pytest
from ortools.linear_solver import pywraplp

from data.models import SessionConfigModel
from domain.shift_model import Shift
from domain.worker_model import Worker
from solver.constraints.base import ConstraintType, SolverContext
from solver.constraints.definitions import register_core_constraints
from solver.constraints.static_soft import (
    AvoidConsecutiveShiftsConstraint,
    MaxHoursPerWeekConstraint,
)
from services.solver_service import _build_constraint_registry
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


def _build_context_for_adjacent_pair_bypass() -> tuple[SolverContext, pywraplp.Variable, pywraplp.Variable, pywraplp.Variable]:
    """Build a worker timeline with S1-roleA, S1-roleB, S2-roleA variables."""
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None

    worker = Worker(name="Alice", worker_id="W1")

    s1_start = datetime(2026, 2, 16, 8, 0)
    s1_end = s1_start + timedelta(hours=8)
    s2_start = s1_end + timedelta(hours=4)  # insufficient rest vs 12h
    s2_end = s2_start + timedelta(hours=8)

    shift_1 = Shift(shift_id="S1", name="Shift1", time_window=TimeWindow(s1_start, s1_end))
    shift_2 = Shift(shift_id="S2", name="Shift2", time_window=TimeWindow(s2_start, s2_end))

    # Two different role vars for same worker+shift.
    var_s1_role_a = solver.IntVar(0, 1, "X_W1_S1_ROLE_A")
    var_s1_role_b = solver.IntVar(0, 1, "X_W1_S1_ROLE_B")
    var_s2_role_a = solver.IntVar(0, 1, "X_W1_S2_ROLE_A")

    # Force the problematic assignment choice:
    # choose role A in S1, do not choose role B, and choose S2.
    solver.Add(var_s1_role_a == 1)
    solver.Add(var_s1_role_b == 0)
    solver.Add(var_s2_role_a == 1)

    context = SolverContext(
        solver=solver,
        x_vars={
            ("W1", "S1", "T1", ("cook",)): var_s1_role_a,
            ("W1", "S1", "T1", ("cashier",)): var_s1_role_b,
            ("W1", "S2", "T2", ("cook",)): var_s2_role_a,
        },
        y_vars={},
        shifts=[shift_1, shift_2],
        workers=[worker],
        worker_shift_assignments={
            ("W1", "S1"): [var_s1_role_a, var_s1_role_b],
            ("W1", "S2"): [var_s2_role_a],
        },
        # Important: ordering is stable for equal starts after sort; this shape
        # makes only (S1-roleB, S2-roleA) adjacent in current implementation.
        worker_global_assignments={
            "W1": [
                (shift_1, var_s1_role_a),
                (shift_1, var_s1_role_b),
                (shift_2, var_s2_role_a),
            ]
        },
        task_metadata={},
    )

    return context, var_s1_role_a, var_s1_role_b, var_s2_role_a


def _build_context_for_forced_overtime() -> SolverContext:
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None

    worker = Worker(name="Alice", worker_id="W1")
    start = datetime(2026, 2, 16, 8, 0)
    end = start + timedelta(hours=16)  # 16h shift to force max-hours slack
    shift = Shift(shift_id="S1", name="LongShift", time_window=TimeWindow(start, end))

    x = solver.IntVar(0, 1, "X_W1_S1")
    solver.Add(x == 1)

    return SolverContext(
        solver=solver,
        x_vars={("W1", "S1", "T1", ()): x},
        y_vars={},
        shifts=[shift],
        workers=[worker],
        worker_shift_assignments={("W1", "S1"): [x]},
        worker_global_assignments={"W1": [(shift, x)]},
        task_metadata={},
    )


def test_regression_multirole_hard_avoid_consecutive_blocks_non_adjacent_var_pair():
    """Regression: HARD consecutive-rest must block multi-role bypass topology."""
    context, _, _, _ = _build_context_for_adjacent_pair_bypass()
    constraint = AvoidConsecutiveShiftsConstraint(
        min_rest_hours=12,
        penalty=-30.0,
        strictness=ConstraintType.HARD,
    )

    constraint.apply(context)
    context.solver.Objective().SetMaximization()
    status = context.solver.Solve()

    assert status == pywraplp.Solver.INFEASIBLE


def test_regression_type_vs_params_strictness_defaults_to_hard_when_type_is_hard(
    db_session, test_session_id
):
    """Regression: top-level HARD must hydrate params.strictness as HARD."""
    try:
        register_core_constraints()
    except ValueError:
        # Global singleton registry may already be initialized in this process.
        pass

    db_session.add(
        SessionConfigModel(
            session_id=test_session_id,
            constraints=[
                {
                    "id": 1,
                    "category": "max_hours_per_week",
                    "type": "HARD",
                    "enabled": True,
                    "params": {"max_hours": 40},
                }
            ],
        )
    )
    db_session.commit()

    registry = _build_constraint_registry(db_session, test_session_id)
    by_name = {constraint.name: constraint for constraint in registry._constraints}
    assert by_name["max_hours_per_week"].type == ConstraintType.HARD


def test_regression_string_strictness_soft_is_coerced_and_reports_violations():
    """Regression: raw string strictness should be coerced to enum and report violations."""
    context = _build_context_for_forced_overtime()
    constraint = MaxHoursPerWeekConstraint(
        max_hours=8,
        penalty_per_hour=-10.0,
        strictness="SOFT",
    )

    constraint.apply(context)
    context.solver.Objective().SetMaximization()
    status = context.solver.Solve()
    assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    assert constraint.type == ConstraintType.SOFT
    assert constraint._slack_vars["W1"].solution_value() > 0.001
    violations = constraint.get_violations(context)
    assert len(violations) == 1
    assert violations[0].constraint_name == "max_hours_per_week"
