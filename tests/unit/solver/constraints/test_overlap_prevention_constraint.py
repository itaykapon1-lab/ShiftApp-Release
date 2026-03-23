"""Isolated mathematical tests for OverlapPreventionConstraint.

OverlapPreventionConstraint is a HARD constraint that prevents a worker
from being assigned to two shifts whose time windows overlap:

    X_shiftA + X_shiftB <= 1   (for overlapping shifts A, B)

These tests verify the constraint makes the model infeasible when both
overlapping shifts are forced, and allows assignment when shifts don't overlap.
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker
from solver.constraints.base import SolverContext
from solver.constraints.static_hard import (
    CoverageConstraint,
    OverlapPreventionConstraint,
)
from tests.unit.solver.constraints.conftest import (
    build_minimal_solver_context,
    MON_MORNING,
    MON_OVERLAP,
    MON_EVENING,
    TUE_MORNING,
)


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_two_shift_context(
    worker: Worker,
    shift_a: Shift,
    shift_b: Shift,
) -> SolverContext:
    """Build a context with one worker eligible for two shifts (one task each)."""
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None

    shifts = [shift_a, shift_b]
    workers = [worker]

    y_vars = {}
    x_vars = {}
    worker_global = defaultdict(list)
    worker_shift = defaultdict(list)
    task_metadata = {}

    for shift in shifts:
        for task in shift.tasks:
            for opt_idx, option in enumerate(task.options):
                y_key = (shift.shift_id, task.task_id, opt_idx)
                y_var = solver.IntVar(0, 1, f"Y_{shift.shift_id}_{task.task_id}_{opt_idx}")
                y_vars[y_key] = y_var
                task_metadata[y_key] = option.requirements

            # Exactly one option per task
            task_y = [y_vars[(shift.shift_id, task.task_id, i)]
                      for i in range(len(task.options))]
            solver.Add(sum(task_y) == 1)

            for option in task.options:
                for req in option.requirements:
                    role_sig = tuple(sorted(req.required_skills.keys()))
                    if all(worker.skills.get(sk, 0) >= lv for sk, lv in req.required_skills.items()):
                        if worker.is_available_for_shift(shift.time_window):
                            x_key = (worker.worker_id, shift.shift_id, task.task_id, role_sig)
                            if x_key not in x_vars:
                                x_var = solver.IntVar(0, 1, f"X_{worker.worker_id}_{shift.shift_id}_{task.task_id}")
                                x_vars[x_key] = x_var
                                worker_global[worker.worker_id].append((shift, x_var))
                                worker_shift[(worker.worker_id, shift.shift_id)].append(x_var)

    return SolverContext(
        solver=solver,
        x_vars=x_vars,
        y_vars=y_vars,
        shifts=shifts,
        workers=workers,
        worker_shift_assignments=dict(worker_shift),
        worker_global_assignments=dict(worker_global),
        task_metadata=task_metadata,
    )


def _make_shift_with_cook_task(shift_id: str, name: str, tw: TimeWindow) -> Shift:
    """Create a shift with a single task requiring 1 Cook."""
    option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
    task = Task(task_id=f"T_{shift_id}", name=f"Task_{name}", options=[option])
    return Shift(shift_id=shift_id, name=name, time_window=tw, tasks=[task])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOverlapPreventionIsolated:
    """OverlapPreventionConstraint must forbid assignment to overlapping shifts."""

    def test_overlapping_shifts_forbid_double_assignment(self):
        """Worker assigned to both overlapping shifts → at most one allowed."""
        # MON_MORNING: 08:00-16:00, MON_OVERLAP: 12:00-20:00 — they overlap
        worker = Worker(
            worker_id="W1", name="Alice", skills={"Cook": 5},
            availability=[TimeWindow(start=datetime(2024, 1, 1, 0, 0),
                                     end=datetime(2024, 1, 1, 23, 59))],
        )
        shift_a = _make_shift_with_cook_task("S_A", "Morning", MON_MORNING)
        shift_b = _make_shift_with_cook_task("S_B", "Overlap", MON_OVERLAP)

        ctx = _build_two_shift_context(worker, shift_a, shift_b)

        # Apply coverage so headcount is enforced
        CoverageConstraint().apply(ctx)
        # Apply overlap prevention
        OverlapPreventionConstraint().apply(ctx)

        # Try to maximize both (push solver to assign both)
        for xv in ctx.x_vars.values():
            ctx.solver.Objective().SetCoefficient(xv, 100.0)
        ctx.solver.Objective().SetMaximization()

        status = ctx.solver.Solve()

        if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            # Worker can be assigned to at most one of the overlapping shifts
            assigned_shifts = [
                s_id for (w_id, s_id, t_id, _), xv in ctx.x_vars.items()
                if xv.solution_value() > 0.5
            ]
            assert len(assigned_shifts) <= 1, (
                f"Worker should be in at most 1 overlapping shift, "
                f"but was assigned to: {assigned_shifts}"
            )
        else:
            # Infeasible is also acceptable — both tasks need 1 Cook but
            # only 1 worker exists and shifts overlap, so one task can't be staffed
            assert status == pywraplp.Solver.INFEASIBLE

    def test_forced_double_assignment_is_infeasible(self):
        """Forcing a worker into both overlapping shifts → INFEASIBLE."""
        worker = Worker(
            worker_id="W1", name="Alice", skills={"Cook": 5},
            availability=[TimeWindow(start=datetime(2024, 1, 1, 0, 0),
                                     end=datetime(2024, 1, 1, 23, 59))],
        )
        shift_a = _make_shift_with_cook_task("S_A", "Morning", MON_MORNING)
        shift_b = _make_shift_with_cook_task("S_B", "Overlap", MON_OVERLAP)

        ctx = _build_two_shift_context(worker, shift_a, shift_b)

        # Force worker into both shifts
        for (w_id, s_id, t_id, _), xv in ctx.x_vars.items():
            ctx.solver.Add(xv == 1)

        OverlapPreventionConstraint().apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status == pywraplp.Solver.INFEASIBLE, (
            f"Forcing worker into both overlapping shifts should be INFEASIBLE, "
            f"got status={status}"
        )

    def test_non_overlapping_shifts_allow_double_assignment(self):
        """Worker can be assigned to two non-overlapping shifts."""
        # MON_MORNING: 08:00-16:00, TUE_MORNING: next day 08:00-16:00 — no overlap
        worker = Worker(
            worker_id="W1", name="Alice", skills={"Cook": 5},
            availability=[MON_MORNING, TUE_MORNING],
        )
        shift_a = _make_shift_with_cook_task("S_MON", "Monday", MON_MORNING)
        shift_b = _make_shift_with_cook_task("S_TUE", "Tuesday", TUE_MORNING)

        ctx = _build_two_shift_context(worker, shift_a, shift_b)

        CoverageConstraint().apply(ctx)
        OverlapPreventionConstraint().apply(ctx)

        # Force both assignments
        for (w_id, s_id, t_id, _), xv in ctx.x_vars.items():
            ctx.solver.Add(xv == 1)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE), (
            f"Non-overlapping shifts should allow both assignments, got status={status}"
        )

        assigned_count = sum(
            1 for xv in ctx.x_vars.values() if xv.solution_value() > 0.5
        )
        assert assigned_count == 2, (
            f"Worker should be assigned to both non-overlapping shifts, "
            f"got {assigned_count}"
        )

    def test_adjacent_shifts_no_overlap(self):
        """Shifts that are exactly back-to-back (no overlap) are allowed.
        MON_MORNING ends at 16:00, MON_EVENING starts at 16:00 → no overlap.
        """
        worker = Worker(
            worker_id="W1", name="Alice", skills={"Cook": 5},
            availability=[TimeWindow(start=datetime(2024, 1, 1, 0, 0),
                                     end=datetime(2024, 1, 1, 23, 59))],
        )
        shift_a = _make_shift_with_cook_task("S_AM", "Morning", MON_MORNING)
        shift_b = _make_shift_with_cook_task("S_PM", "Evening", MON_EVENING)

        ctx = _build_two_shift_context(worker, shift_a, shift_b)

        CoverageConstraint().apply(ctx)
        OverlapPreventionConstraint().apply(ctx)

        # Force both
        for xv in ctx.x_vars.values():
            ctx.solver.Add(xv == 1)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE), (
            f"Adjacent non-overlapping shifts should be feasible, got status={status}"
        )

    def test_three_shifts_two_overlapping(self):
        """3 shifts where A overlaps B but not C → worker in at most one of {A,B} + C.

        This test isolates the overlap constraint only (no coverage) to avoid
        infeasibility from headcount requirements exceeding available workers.
        """
        full_day = TimeWindow(start=datetime(2024, 1, 1, 0, 0),
                              end=datetime(2024, 1, 2, 23, 59))
        worker = Worker(
            worker_id="W1", name="Alice", skills={"Cook": 5},
            availability=[full_day],
        )

        shift_a = Shift(shift_id="S_A", name="Morning", time_window=MON_MORNING)
        shift_b = Shift(shift_id="S_B", name="Overlap", time_window=MON_OVERLAP)
        shift_c = Shift(shift_id="S_C", name="NextDay", time_window=TUE_MORNING)

        # Build a 3-shift context with raw X variables only (no tasks/coverage)
        solver = pywraplp.Solver.CreateSolver("SCIP")
        shifts = [shift_a, shift_b, shift_c]
        x_vars = {}
        wg = defaultdict(list)
        ws = defaultdict(list)

        for shift in shifts:
            xk = (worker.worker_id, shift.shift_id, "T_dummy", ("Cook",))
            xv = solver.IntVar(0, 1, f"X_W1_{shift.shift_id}")
            x_vars[xk] = xv
            wg[worker.worker_id].append((shift, xv))
            ws[(worker.worker_id, shift.shift_id)].append(xv)

        ctx = SolverContext(
            solver=solver, x_vars=x_vars, y_vars={},
            shifts=shifts, workers=[worker],
            worker_shift_assignments=dict(ws),
            worker_global_assignments=dict(wg),
            task_metadata={},
        )

        # Apply ONLY overlap prevention (no coverage — we're testing overlap in isolation)
        OverlapPreventionConstraint().apply(ctx)

        # Reward all assignments equally — push solver to assign all 3
        for xv in ctx.x_vars.values():
            ctx.solver.Objective().SetCoefficient(xv, 10.0)
        ctx.solver.Objective().SetMaximization()

        status = ctx.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        assigned = {
            s_id for (w_id, s_id, t_id, _), xv in ctx.x_vars.items()
            if xv.solution_value() > 0.5
        }

        # A and B overlap → can't both be in the set
        assert not ({"S_A", "S_B"} <= assigned), (
            f"Worker should not be assigned to both overlapping shifts A and B, "
            f"but was assigned to: {assigned}"
        )
        # Should be assigned to 2 shifts max (one of {A,B} + C)
        assert len(assigned) == 2, (
            f"Expected 2 non-overlapping shift assignments, got {len(assigned)}: {assigned}"
        )
