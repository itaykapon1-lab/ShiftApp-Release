"""
Implementation of static soft constraints (Preferences).

This module contains "nice-to-have" rules that optimize the schedule quality.
Unlike hard constraints, these rules do not block the solver from finding a
solution. Instead, they use 'Slack Variables' or 'Indicator Variables' to
apply penalties to the objective function when violated.
"""
import logging
from typing import Dict, List, Tuple, Optional

from ortools.linear_solver import pywraplp

from app.core.constants import (
    EPSILON,
    MAX_HOURS_PER_WEEK_DEFAULT,
    MAX_HOURS_PER_WEEK_PENALTY,
    CONSECUTIVE_REST_HOURS_DEFAULT,
    CONSECUTIVE_REST_PENALTY,
    WORKER_PREFERENCE_REWARD,
    WORKER_PREFERENCE_PENALTY,
    TASK_PRIORITY_BASE_PENALTY,
)
from solver.constraints.base import (
    BaseConstraint,
    ConstraintType,
    ConstraintKind,
    SolverContext,
    ConstraintViolation
)

logger = logging.getLogger(__name__)


def _coerce_type(v: ConstraintType | str, default: ConstraintType) -> ConstraintType:
    """Normalize strictness inputs to a ConstraintType enum."""
    if isinstance(v, ConstraintType):
        return v
    if isinstance(v, str):
        normalized = v.strip().lower()
        if normalized in {"hard", "soft"}:
            return ConstraintType(normalized)
    logger.warning("Invalid strictness value '%s'; defaulting to %s", v, default.value)
    return default


class MaxHoursPerWeekConstraint(BaseConstraint):
    """Soft Constraint: Penalizes workers exceeding a weekly hour limit.

    This constraint calculates the total duration of shifts assigned to each
    worker. If the total exceeds 'max_hours', a slack variable captures the
    excess, and a penalty is applied per excess hour.

    Attributes:
        max_hours (int): The threshold for weekly hours (e.g., 40).
        penalty_per_hour (float): Cost subtracted from objective per excess hour.
    """

    def __init__(
        self,
        max_hours: int = MAX_HOURS_PER_WEEK_DEFAULT,
        penalty_per_hour: float = MAX_HOURS_PER_WEEK_PENALTY,
        strictness: ConstraintType | str = ConstraintType.SOFT,
    ):
        """Initializes the max hours constraint.

        Args:
            max_hours: Maximum hours allowed before penalty kicks in.
            penalty_per_hour: The score deduction per hour over the limit.
                              Should be negative for maximization problems.
            strictness: Whether this constraint is HARD (infeasible if violated)
                or SOFT (penalty applied). Defaults to SOFT for backward compat.
        """
        strictness = _coerce_type(strictness, ConstraintType.SOFT)
        super().__init__(
            name="max_hours_per_week",
            constraint_type=strictness,
            kind=ConstraintKind.STATIC
        )
        self.max_hours = max_hours
        self.penalty_per_hour = penalty_per_hour

        # Internal storage to retrieve variables during get_violations()
        # Key: worker_id -> Value: slack_variable
        self._slack_vars: Dict[str, pywraplp.Variable] = {}

    def apply(self, context: SolverContext) -> None:
        """Creates slack variables for hour overages.

        Mathematical Formulation:
            Let X_i be the assignment variable for shift i.
            Let D_i be the duration of shift i in hours.
            Let S_w be the slack variable for worker w (S_w >= 0).

            Constraint: Sum(X_i * D_i) - S_w <= max_hours
            Objective:  Maximize ... + (S_w * penalty_per_hour)
        """
        self._slack_vars.clear()

        for worker in context.workers:
            # 1. Build the expression for total hours assigned to this worker
            total_hours_expr = 0
            has_assignments = False

            # We iterate through all potential assignments for this worker
            # Context provides this pre-grouped by shift for efficiency.
            assignments = []
            # Note: We need to flatten the list of lists from worker_shift_assignments
            # or iterate over worker_global_assignments. Global is cleaner here.
            if worker.worker_id in context.worker_global_assignments:
                assignments = context.worker_global_assignments[worker.worker_id]

            for shift, x_var in assignments:
                duration_hours = shift.time_window.duration_hours
                total_hours_expr += duration_hours * x_var
                has_assignments = True

            if not has_assignments:
                continue

            if self.type == ConstraintType.HARD:
                # HARD: strictly forbid exceeding max_hours — no slack variable
                context.solver.Add(total_hours_expr <= self.max_hours)
            else:
                # SOFT: existing slack-variable penalty (unchanged)
                slack_name = f"slack_hours_{worker.worker_id}"
                slack_var = context.solver.NumVar(
                    0.0, context.solver.infinity(), slack_name
                )

                # Store for later reporting
                self._slack_vars[worker.worker_id] = slack_var

                # Add the Constraint: Total - Slack <= Max
                context.solver.Add(total_hours_expr - self.max_hours <= slack_var)

                # Update Objective: Apply penalty
                context.solver.Objective().SetCoefficient(
                    slack_var, self.penalty_per_hour
                )

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """Checks slack variables to identify workers who worked overtime."""
        if self.type != ConstraintType.SOFT:
            return []

        violations = []

        for worker_id, slack_var in self._slack_vars.items():
            excess_hours = slack_var.solution_value()

            # If slack > epsilon, we have a violation
            if excess_hours > EPSILON:
                total_hours = self.max_hours + excess_hours
                total_penalty = excess_hours * self.penalty_per_hour

                violations.append(ConstraintViolation(
                    constraint_name=self.name,
                    description=f"Worker {worker_id} exceeded limit by {excess_hours:.2f} hours.",
                    penalty=total_penalty,
                    observed_value=total_hours,
                    limit_value=self.max_hours
                ))

        return violations


class AvoidConsecutiveShiftsConstraint(BaseConstraint):
    """Soft Constraint: Penalizes back-to-back shifts with insufficient rest.

    This constraint identifies pairs of adjacent shifts assigned to the same
    worker. If the time gap between them is less than 'min_rest_hours',
    it flags a violation and applies a fixed penalty.

    Attributes:
        min_rest_hours (int): Minimum required hours between shift end and next start.
        penalty (float): Fixed cost subtracted from objective per violation.
    """

    def __init__(
        self,
        min_rest_hours: int = CONSECUTIVE_REST_HOURS_DEFAULT,
        penalty: float = CONSECUTIVE_REST_PENALTY,
        strictness: ConstraintType | str = ConstraintType.SOFT,
    ):
        """Initializes the consecutive shift constraint.

        Args:
            min_rest_hours: Required rest period in hours.
            penalty: Fixed deduction for each violation occurrence.
            strictness: Whether this constraint is HARD (infeasible if violated)
                or SOFT (penalty applied). Defaults to SOFT for backward compat.
        """
        strictness = _coerce_type(strictness, ConstraintType.SOFT)
        super().__init__(
            name="avoid_consecutive_shifts",
            constraint_type=strictness,
            kind=ConstraintKind.STATIC
        )
        self.min_rest_hours = min_rest_hours
        self.penalty = penalty

        # Internal storage for reporting
        # List of tuples: (WorkerID, ShiftA_ID, ShiftB_ID, ViolationIndicatorVar, ActualRest)
        self._violation_markers: List[Tuple[str, str, str, pywraplp.Variable, float]] = []

    def apply(self, context: SolverContext) -> None:
        """Detects tight schedules and creates indicator variables.

        Optimization Note:
            Leverages `worker_global_assignments` which is already grouped by worker.
            Sorts assignments by time to perform a linear O(N) scan per worker.
        """
        self._violation_markers.clear()

        for w_id, assignment_list in context.worker_global_assignments.items():
            # Build a shift-level timeline (dedupe multi-role vars within same shift).
            # Key: shift_id -> Shift object.
            shift_by_id = {}
            for shift, _ in assignment_list:
                shift_by_id.setdefault(shift.shift_id, shift)

            ordered_shifts = sorted(
                shift_by_id.values(),
                key=lambda s: s.time_window.start
            )

            if len(ordered_shifts) < 2:
                continue

            for i in range(len(ordered_shifts) - 1):
                shift_a = ordered_shifts[i]
                shift_b = ordered_shifts[i + 1]

                # Calculate rest time
                delta = shift_b.time_window.start - shift_a.time_window.end
                rest_hours = delta.total_seconds() / 3600.0

                # Check if this pair violates the rule
                if 0 <= rest_hours < self.min_rest_hours:
                    vars_a = context.worker_shift_assignments.get((w_id, shift_a.shift_id), [])
                    vars_b = context.worker_shift_assignments.get((w_id, shift_b.shift_id), [])
                    is_working_a = sum(vars_a)
                    is_working_b = sum(vars_b)

                    if self.type == ConstraintType.HARD:
                        # HARD: forbid being assigned in both violating shifts.
                        context.solver.Add(is_working_a + is_working_b <= 1)
                    else:
                        # SOFT: existing indicator-variable penalty (unchanged)
                        violation_name = (
                            f"consecutive_viol_{w_id}_"
                            f"{shift_a.shift_id}_{shift_b.shift_id}"
                        )
                        violation_var = context.solver.BoolVar(violation_name)

                        # violation_var >= var_a + var_b - 1
                        context.solver.Add(
                            violation_var >= is_working_a + is_working_b - 1
                        )

                        # Update Objective
                        context.solver.Objective().SetCoefficient(
                            violation_var, self.penalty
                        )

                        # Save context for reporting
                        self._violation_markers.append((
                            w_id,
                            shift_a.shift_id,
                            shift_b.shift_id,
                            violation_var,
                            rest_hours
                        ))

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """Checks which indicator variables were triggered in the solution."""
        if self.type != ConstraintType.SOFT:
            return []

        violations = []

        for w_id, s_a, s_b, v_var, rest_hours in self._violation_markers:
            if v_var.solution_value() > 0.5:
                violations.append(ConstraintViolation(
                    constraint_name=self.name,
                    description=(f"Worker {w_id} has insufficient rest ({rest_hours:.1f}h) "
                                 f"between shifts {s_a} and {s_b}."),
                    penalty=self.penalty,
                    observed_value=rest_hours,
                    limit_value=self.min_rest_hours
                ))

        return violations


class WorkerPreferencesConstraint(BaseConstraint):
    """Soft Constraint: Rewards/Penalizes assignments based on worker preferences.

    Uses configurable reward/penalty values instead of raw domain scores.
    The raw score from worker.calculate_preference_score() is used only as a
    directional signal (positive = preferred, negative = unwanted, zero = neutral).

    Attributes:
        preference_reward: Points added for preferred shift assignments.
        preference_penalty: Points subtracted for unwanted shift assignments.
    """

    def __init__(
        self,
        preference_reward: int = WORKER_PREFERENCE_REWARD,
        preference_penalty: int = WORKER_PREFERENCE_PENALTY,
    ):
        """Initializes the worker preferences constraint.

        Args:
            preference_reward: Positive score applied when a worker is assigned
                a shift they prefer. Must be >= 1.
            preference_penalty: Negative score applied when a worker is assigned
                a shift they want to avoid. Must be <= -1.
        """
        super().__init__(
            name="worker_preferences",
            constraint_type=ConstraintType.SOFT,
            kind=ConstraintKind.STATIC
        )
        self.preference_reward = preference_reward
        self.preference_penalty = preference_penalty

    def apply(self, context: SolverContext) -> None:
        """Applies preference scores to the assignment variables."""

        # 1. Create optimization maps for O(1) lookup
        shift_map = {s.shift_id: s for s in context.shifts}
        worker_map = {w.worker_id: w for w in context.workers}
        updates_count = 0
        match_attempts = 0
        
        # 2. Iterate over all assignment variables (X)
        for key, x_var in context.x_vars.items():
            w_id, s_id, t_id, role_sig = key

            worker = worker_map.get(w_id)
            shift = shift_map.get(s_id)

            if worker and shift:
                match_attempts += 1

                # 3. Fetch the raw directional signal from the Domain Model
                raw_score = worker.calculate_preference_score(shift.time_window)

                # 4. Map raw signal to configured reward/penalty values
                if raw_score > 0:
                    score = self.preference_reward
                elif raw_score < 0:
                    score = self.preference_penalty
                else:
                    score = 0

                # 5. Update the Objective Function
                if score != 0:
                    current_coeff = context.solver.Objective().GetCoefficient(x_var)
                    new_coeff = score + current_coeff
                    context.solver.Objective().SetCoefficient(x_var, new_coeff)
                    verified_coeff = context.solver.Objective().GetCoefficient(x_var)

                    if verified_coeff != new_coeff:
                        logger.error(
                            f"CRITICAL: Failed to update variable {x_var.name()}. Expected {new_coeff}, got {verified_coeff}")
                    else:
                        updates_count += 1
                        logger.debug(f"Updated {x_var.name()} -> Coeff: {verified_coeff} (Score: {score})")
        
        logger.info(f"WorkerPreferencesConstraint: {match_attempts} checked, {updates_count} updated")

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """
        Optional: We can report on 'Negative Preferences' (Shift violations).
        If a worker was assigned to a shift they marked with '!', we report it.
        """
        violations = []
        shift_map = {s.shift_id: s for s in context.shifts}
        worker_map = {w.worker_id: w for w in context.workers}

        for key, x_var in context.x_vars.items():
            # Check only assigned shifts
            if x_var.solution_value() > 0.5:
                w_id, s_id, _, _ = key
                worker = worker_map.get(w_id)
                shift = shift_map.get(s_id)

                if worker and shift:
                    raw_score = worker.calculate_preference_score(shift.time_window)
                    # If raw score is negative, it's a violation of preference
                    if raw_score < 0:
                        violations.append(ConstraintViolation(
                            constraint_name=self.name,
                            description=f"Worker {worker.name} assigned to unwanted shift {shift.name}",
                            penalty=self.preference_penalty,
                            observed_value=1,
                            limit_value=0
                        ))
        return violations


class TaskOptionPriorityConstraint(BaseConstraint):
    """Soft Constraint: Penalizes selection of lower-priority task options.

    When a task has multiple options with different priorities (1=best, 5=worst),
    this constraint applies a configurable penalty for choosing non-preferred
    options: ``penalty = base_penalty * (priority - 1)``.

    Always SOFT — a HARD version would force #1 always, making alternatives
    pointless.

    Attributes:
        base_penalty: Penalty multiplied by ``(priority - 1)`` for each
            non-#1 option selected.
    """

    def __init__(self, base_penalty: float = TASK_PRIORITY_BASE_PENALTY):
        """Initializes the task option priority constraint.

        Args:
            base_penalty: Penalty per priority level above #1. Should be
                negative for maximization problems.
        """
        super().__init__(
            name="task_option_priority",
            constraint_type=ConstraintType.SOFT,
            kind=ConstraintKind.STATIC,
        )
        self.base_penalty = base_penalty
        # Stores (shift_name, task_name, priority, penalty, y_var) for violation reporting
        self._penalized_options: List[Tuple[str, str, int, float, pywraplp.Variable]] = []

    def apply(self, context: SolverContext) -> None:
        """Adds penalty coefficients to Y vars for lower-priority options.

        Mathematical Formulation:
            For each Y_var associated with option priority P > 1:
            Objective coefficient += base_penalty * (P - 1)

        This composes additively with existing ``preference_score``
        coefficients already set on Y vars by solver_engine.py.
        """
        self._penalized_options.clear()

        for shift in context.shifts:
            for task in shift.tasks:
                for opt_idx, option in enumerate(task.options):
                    priority = getattr(option, 'priority', 1)
                    if priority <= 1:
                        continue  # no penalty for #1

                    y_key = (shift.shift_id, task.task_id, opt_idx)
                    y_var = context.y_vars.get(y_key)
                    if y_var is None:
                        continue

                    penalty = self.base_penalty * (priority - 1)
                    current = context.solver.Objective().GetCoefficient(y_var)
                    context.solver.Objective().SetCoefficient(y_var, current + penalty)

                    self._penalized_options.append(
                        (shift.name, task.name, priority, penalty, y_var)
                    )

        logger.info(
            "TaskOptionPriorityConstraint: penalized %d non-#1 options",
            len(self._penalized_options),
        )

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """Reports violations for selected options with priority > 1.

        Returns:
            List[ConstraintViolation]: One violation per penalized Y var
                that was selected in the solution.
        """
        violations = []

        for shift_name, task_name, priority, penalty, y_var in self._penalized_options:
            if y_var.solution_value() > 0.5:
                violations.append(ConstraintViolation(
                    constraint_name=self.name,
                    description=(
                        f"Shift '{shift_name}', task '{task_name}': "
                        f"selected option with priority #{priority} "
                        f"(penalty: {penalty:.1f})."
                    ),
                    penalty=penalty,
                    observed_value=priority,
                    limit_value=1,
                ))

        return violations
