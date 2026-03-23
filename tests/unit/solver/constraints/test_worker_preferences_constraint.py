"""Isolated mathematical tests for WorkerPreferencesConstraint.

WorkerPreferencesConstraint is a SOFT constraint that adjusts objective
function coefficients on X variables based on worker availability preferences:

    raw_score > 0  →  coefficient += WORKER_PREFERENCE_REWARD  (+10)
    raw_score < 0  →  coefficient += WORKER_PREFERENCE_PENALTY  (-100)
    raw_score == 0 →  no change

These tests verify the correct objective coefficients are set and that
the solver's assignment decisions are influenced by preference scores.
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Tuple

import pytest
from ortools.linear_solver import pywraplp

from app.core.constants import WORKER_PREFERENCE_REWARD, WORKER_PREFERENCE_PENALTY
from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker
from solver.constraints.base import SolverContext
from solver.constraints.static_hard import CoverageConstraint
from solver.constraints.static_soft import WorkerPreferencesConstraint
from tests.unit.solver.constraints.conftest import (
    build_minimal_solver_context,
    MON_MORNING,
    TUE_MORNING,
)


pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_preference_context(
    workers: List[Worker],
    shifts: List[Shift],
) -> SolverContext:
    """Build a context with the given workers and shifts."""
    return build_minimal_solver_context(workers=workers, shifts=shifts)


def _make_worker_with_preference(
    worker_id: str,
    name: str,
    skills: dict,
    availability: List[TimeWindow],
    preferences: Dict[TimeWindow, int],
) -> Worker:
    """Create a worker with explicit preferences."""
    w = Worker(
        worker_id=worker_id, name=name, skills=skills, availability=availability,
    )
    for tw, score in preferences.items():
        w.add_preference(tw, score)
    return w


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWorkerPreferencesIsolated:
    """WorkerPreferencesConstraint must set correct objective coefficients."""

    def test_preferred_shift_gets_positive_coefficient(self):
        """A worker who prefers a shift gets +WORKER_PREFERENCE_REWARD on their X var."""
        # Alice prefers Monday Morning (positive score)
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: 10},  # positive = preferred
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        # Check coefficient before
        x_key = ("W_ALICE", "S1", "T1", ("Cook",))
        x_var = ctx.x_vars.get(x_key)
        assert x_var is not None, f"X var should exist for eligible worker. Keys: {list(ctx.x_vars.keys())}"

        coeff_before = ctx.solver.Objective().GetCoefficient(x_var)

        # Apply preferences
        pref_constraint = WorkerPreferencesConstraint()
        pref_constraint.apply(ctx)

        coeff_after = ctx.solver.Objective().GetCoefficient(x_var)

        # The coefficient should have increased by WORKER_PREFERENCE_REWARD
        expected_delta = WORKER_PREFERENCE_REWARD  # +10
        actual_delta = coeff_after - coeff_before

        assert actual_delta == expected_delta, (
            f"Expected coefficient to increase by {expected_delta} (WORKER_PREFERENCE_REWARD), "
            f"but delta was {actual_delta}. Before={coeff_before}, After={coeff_after}"
        )

    def test_unwanted_shift_gets_negative_coefficient(self):
        """A worker who dislikes a shift gets +WORKER_PREFERENCE_PENALTY on their X var."""
        # Alice dislikes Monday Morning (negative score)
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: -5},  # negative = unwanted
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        x_key = ("W_ALICE", "S1", "T1", ("Cook",))
        x_var = ctx.x_vars[x_key]
        coeff_before = ctx.solver.Objective().GetCoefficient(x_var)

        pref_constraint = WorkerPreferencesConstraint()
        pref_constraint.apply(ctx)

        coeff_after = ctx.solver.Objective().GetCoefficient(x_var)
        actual_delta = coeff_after - coeff_before

        expected_delta = WORKER_PREFERENCE_PENALTY  # -100
        assert actual_delta == expected_delta, (
            f"Expected coefficient to change by {expected_delta} (WORKER_PREFERENCE_PENALTY), "
            f"but delta was {actual_delta}. Before={coeff_before}, After={coeff_after}"
        )

    def test_neutral_preference_no_coefficient_change(self):
        """A worker with no preference for a shift gets no coefficient change."""
        # Alice has no preference for Monday Morning (score = 0)
        alice = Worker(
            worker_id="W_ALICE", name="Alice", skills={"Cook": 5},
            availability=[MON_MORNING],
            # No preferences set → calculate_preference_score returns 0
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        x_key = ("W_ALICE", "S1", "T1", ("Cook",))
        x_var = ctx.x_vars[x_key]
        coeff_before = ctx.solver.Objective().GetCoefficient(x_var)

        pref_constraint = WorkerPreferencesConstraint()
        pref_constraint.apply(ctx)

        coeff_after = ctx.solver.Objective().GetCoefficient(x_var)

        assert coeff_after == coeff_before, (
            f"Neutral preference should not change coefficient. "
            f"Before={coeff_before}, After={coeff_after}"
        )

    def test_solver_prefers_preferred_worker_over_neutral(self):
        """Given 2 workers for 1 slot, solver assigns the one who prefers the shift."""
        # Alice prefers the shift, Bob is neutral
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: 10},
        )
        bob = Worker(
            worker_id="W_BOB", name="Bob", skills={"Cook": 5},
            availability=[MON_MORNING],
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice, bob], shifts=[shift])

        CoverageConstraint().apply(ctx)
        WorkerPreferencesConstraint().apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        alice_assigned = any(
            xv.solution_value() > 0.5
            for (w_id, s_id, t_id, _), xv in ctx.x_vars.items()
            if w_id == "W_ALICE"
        )
        assert alice_assigned, (
            "Solver should prefer Alice (who likes the shift) over Bob (neutral)"
        )

    def test_solver_avoids_unwanted_assignment_when_alternative_exists(self):
        """Given 2 workers where one dislikes the shift, solver picks the other."""
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: -5},  # Alice dislikes
        )
        bob = Worker(
            worker_id="W_BOB", name="Bob", skills={"Cook": 5},
            availability=[MON_MORNING],
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice, bob], shifts=[shift])

        CoverageConstraint().apply(ctx)
        WorkerPreferencesConstraint().apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()

        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        bob_assigned = any(
            xv.solution_value() > 0.5
            for (w_id, s_id, t_id, _), xv in ctx.x_vars.items()
            if w_id == "W_BOB"
        )
        assert bob_assigned, (
            "Solver should avoid Alice (who dislikes the shift) and pick Bob"
        )

    def test_custom_reward_penalty_values(self):
        """WorkerPreferencesConstraint respects custom reward/penalty values."""
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: 10},
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        x_key = ("W_ALICE", "S1", "T1", ("Cook",))
        x_var = ctx.x_vars[x_key]
        coeff_before = ctx.solver.Objective().GetCoefficient(x_var)

        # Use custom values
        custom_reward = 50
        custom_penalty = -200
        pref = WorkerPreferencesConstraint(
            preference_reward=custom_reward,
            preference_penalty=custom_penalty,
        )
        pref.apply(ctx)

        coeff_after = ctx.solver.Objective().GetCoefficient(x_var)
        actual_delta = coeff_after - coeff_before

        assert actual_delta == custom_reward, (
            f"Expected custom reward {custom_reward}, got delta {actual_delta}"
        )

    def test_coefficient_is_additive_with_existing(self):
        """Preference coefficient composes additively with pre-existing coefficients."""
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: 10},
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        x_key = ("W_ALICE", "S1", "T1", ("Cook",))
        x_var = ctx.x_vars[x_key]

        # Pre-set a coefficient (simulating another constraint's contribution)
        pre_existing = 7.0
        ctx.solver.Objective().SetCoefficient(x_var, pre_existing)

        WorkerPreferencesConstraint().apply(ctx)

        coeff_after = ctx.solver.Objective().GetCoefficient(x_var)
        expected = pre_existing + WORKER_PREFERENCE_REWARD

        assert coeff_after == expected, (
            f"Coefficient should be additive: {pre_existing} + {WORKER_PREFERENCE_REWARD} "
            f"= {expected}, got {coeff_after}"
        )

    def test_violation_reported_for_unwanted_assignment(self):
        """get_violations reports when a worker is assigned to an unwanted shift."""
        # Only Alice can cook, and she dislikes it — solver is forced to assign her
        alice = _make_worker_with_preference(
            "W_ALICE", "Alice", {"Cook": 5},
            availability=[MON_MORNING],
            preferences={MON_MORNING: -5},
        )

        option = TaskOption(requirements=[Requirement(count=1, required_skills={"Cook": 1})])
        task = Task(task_id="T1", name="Kitchen", options=[option])
        shift = Shift(shift_id="S1", name="Monday Morning", time_window=MON_MORNING, tasks=[task])

        ctx = build_minimal_solver_context(workers=[alice], shifts=[shift])

        CoverageConstraint().apply(ctx)
        pref = WorkerPreferencesConstraint()
        pref.apply(ctx)

        ctx.solver.Objective().SetMaximization()
        status = ctx.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        violations = pref.get_violations(ctx)
        assert len(violations) >= 1, (
            f"Expected at least 1 violation for unwanted assignment, got {len(violations)}"
        )
        assert violations[0].penalty == WORKER_PREFERENCE_PENALTY, (
            f"Violation penalty should be {WORKER_PREFERENCE_PENALTY}, "
            f"got {violations[0].penalty}"
        )
