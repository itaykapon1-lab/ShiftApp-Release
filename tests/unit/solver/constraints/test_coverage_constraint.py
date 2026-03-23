"""Isolated mathematical tests for CoverageConstraint.

CoverageConstraint is a HARD constraint that links X (worker assignment)
and Y (option selection) variables:

    Sum(X_workers_for_role) == Sum(Y_option * Required_Count_For_Option)

These tests verify the constraint forces EXACTLY the required headcount
for the selected option, using a minimal solver context.
"""

from collections import defaultdict
from datetime import datetime
from typing import List

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker
from solver.constraints.base import SolverContext
from solver.constraints.static_hard import CoverageConstraint
from tests.unit.solver.constraints.conftest import (
    build_minimal_solver_context,
    MON_MORNING,
    TUE_MORNING,
)


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCoverageConstraintIsolated:
    """CoverageConstraint must force exactly the required headcount."""

    def test_single_option_single_role_exact_headcount(self):
        """1 task option needing 1 Cook → exactly 1 Cook must be assigned."""
        ctx = build_minimal_solver_context()

        coverage = CoverageConstraint()
        coverage.apply(ctx)

        # Maximise to assign as many workers as possible (to verify coverage
        # doesn't allow over-staffing)
        for x_var in ctx.x_vars.values():
            ctx.solver.Objective().SetCoefficient(x_var, 1.0)
        ctx.solver.Objective().SetMaximization()

        status = ctx.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE), (
            f"Expected feasible solution, got status={status}"
        )

        # Count assigned cooks for Monday Morning Kitchen task
        cook_assigned = 0
        for (w_id, s_id, t_id, role_sig), x_var in ctx.x_vars.items():
            if s_id == "S_MON_AM" and t_id == "T_KITCHEN" and x_var.solution_value() > 0.5:
                cook_assigned += 1

        assert cook_assigned == 1, (
            f"Coverage constraint should force exactly 1 Cook, got {cook_assigned}"
        )

    def test_multi_option_higher_headcount_selected(self):
        """2 options: Option A needs 1 Cook, Option B needs 2 Cooks.
        With reward on Option B, solver should select B and assign 2 Cooks.
        """
        # 3 cooks available
        workers = [
            Worker(worker_id=f"W{i}", name=f"Cook{i}", skills={"Cook": 5},
                   availability=[MON_MORNING])
            for i in range(3)
        ]

        # Task with 2 options at different headcounts
        option_a = TaskOption(
            requirements=[Requirement(count=1, required_skills={"Cook": 1})],
            preference_score=0,
        )
        option_b = TaskOption(
            requirements=[Requirement(count=2, required_skills={"Cook": 1})],
            preference_score=100,  # Heavily prefer Option B
        )
        task = Task(task_id="T1", name="Kitchen", options=[option_a, option_b])
        shift = Shift(shift_id="S1", name="Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=workers, shifts=[shift])

        coverage = CoverageConstraint()
        coverage.apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        # Option B (index 1) should be selected
        y_b = ctx.y_vars.get(("S1", "T1", 1))
        assert y_b is not None
        assert y_b.solution_value() > 0.5, "Option B should be selected (higher preference)"

        # Exactly 2 cooks should be assigned (matching Option B's requirement)
        cooks_assigned = sum(
            1 for (w_id, s_id, t_id, _), xv in ctx.x_vars.items()
            if s_id == "S1" and t_id == "T1" and xv.solution_value() > 0.5
        )
        assert cooks_assigned == 2, (
            f"Option B requires 2 Cooks, but {cooks_assigned} were assigned"
        )

    def test_zero_eligible_workers_makes_infeasible(self):
        """A task requiring a skill no worker has → model is infeasible."""
        # Workers only have "Cook", task needs "Pilot"
        workers = [
            Worker(worker_id="W1", name="Alice", skills={"Cook": 5},
                   availability=[MON_MORNING]),
        ]
        option = TaskOption(
            requirements=[Requirement(count=1, required_skills={"Pilot": 1})],
        )
        task = Task(task_id="T1", name="Aviation", options=[option])
        shift = Shift(shift_id="S1", name="Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=workers, shifts=[shift])

        coverage = CoverageConstraint()
        coverage.apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        # No X variables exist for the "Pilot" role, but coverage demands
        # sum(X) == 1 → infeasible (0 == 1 is impossible)
        assert status == pywraplp.Solver.INFEASIBLE, (
            f"Expected INFEASIBLE when no workers can fill the role, got status={status}"
        )

    def test_multiple_roles_in_single_option(self):
        """An option needing 1 Cook AND 1 Waiter → both roles must be filled."""
        workers = [
            Worker(worker_id="W_ALICE", name="Alice", skills={"Cook": 5},
                   availability=[MON_MORNING]),
            Worker(worker_id="W_BOB", name="Bob", skills={"Waiter": 5},
                   availability=[MON_MORNING]),
        ]
        option = TaskOption(
            requirements=[
                Requirement(count=1, required_skills={"Cook": 1}),
                Requirement(count=1, required_skills={"Waiter": 1}),
            ],
        )
        task = Task(task_id="T1", name="Full Service", options=[option])
        shift = Shift(shift_id="S1", name="Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=workers, shifts=[shift])

        coverage = CoverageConstraint()
        coverage.apply(ctx)

        for xv in ctx.x_vars.values():
            ctx.solver.Objective().SetCoefficient(xv, 1.0)
        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        # Count assignments by role
        cook_count = sum(
            1 for (w_id, s_id, t_id, role), xv in ctx.x_vars.items()
            if "Cook" in role and xv.solution_value() > 0.5
        )
        waiter_count = sum(
            1 for (w_id, s_id, t_id, role), xv in ctx.x_vars.items()
            if "Waiter" in role and xv.solution_value() > 0.5
        )

        assert cook_count == 1, f"Expected 1 Cook assigned, got {cook_count}"
        assert waiter_count == 1, f"Expected 1 Waiter assigned, got {waiter_count}"

    def test_headcount_not_exceeded(self):
        """With 5 eligible workers and headcount=2, exactly 2 must be assigned."""
        workers = [
            Worker(worker_id=f"W{i}", name=f"Cook{i}", skills={"Cook": 5},
                   availability=[MON_MORNING])
            for i in range(5)
        ]
        option = TaskOption(
            requirements=[Requirement(count=2, required_skills={"Cook": 1})],
        )
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=workers, shifts=[shift])

        coverage = CoverageConstraint()
        coverage.apply(ctx)

        # Reward every assignment to try to over-staff
        for xv in ctx.x_vars.values():
            ctx.solver.Objective().SetCoefficient(xv, 10.0)
        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        assigned = sum(
            1 for xv in ctx.x_vars.values() if xv.solution_value() > 0.5
        )
        assert assigned == 2, (
            f"Coverage should enforce exactly 2 assignments (headcount=2), "
            f"but {assigned} workers were assigned"
        )
