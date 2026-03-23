"""
Implementation of static hard constraints.

This module contains the core scheduling rules that must always be satisfied.
These constraints form the backbone of a valid schedule (feasibility).
They correspond to the logic previously hardcoded in the solver engine.
"""

from collections import defaultdict
from typing import List, Tuple, Dict, Any

from ortools.linear_solver import pywraplp

from solver.constraints.base import (
    BaseConstraint,
    ConstraintType,
    ConstraintKind,
    SolverContext
)


class CoverageConstraint(BaseConstraint):
    """Ensures tasks are staffed exactly according to the selected option requirements.

    This constraint links the Decision Variables X (Worker Assignments) with
    Decision Variables Y (Option Selection).

    Formula:
        For each specific Role in a Task:
        Sum(X_workers_assigned_to_role) == Sum(Option_Y * Required_Count_For_Option)

    Example:
        If Option A requires 2 Waiters and Option B requires 3 Waiters:
        Sum(X_waiters) == (2 * Y_OptionA) + (3 * Y_OptionB)
    """

    def __init__(self):
        """Initializes the coverage constraint."""
        super().__init__(
            name="coverage",
            constraint_type=ConstraintType.HARD,
            kind=ConstraintKind.STATIC
        )

    def apply(self, context: SolverContext) -> None:
        """Applies the coverage logic to the solver context.

        Optimization Note:
            We pre-index x_vars by (shift_id, task_id, role_sig) to avoid
            iterating over the entire x_vars dictionary for every role requirement.
            This reduces complexity from O(Tasks * Total_Vars) to O(Total_Vars).
        """
        # 1. Pre-index X variables for O(1) lookup by (shift, task, role).
        # This avoids an O(Tasks * Total_Vars) scan; instead, each role's
        # assigned-worker variables can be fetched in O(1).
        # Key: (shift_id, task_id, role_signature) -> Value: List[x_var]
        x_vars_by_role: Dict[Tuple[str, str, Any], List[pywraplp.Variable]] = defaultdict(list)

        for (w_id, s_id, t_id, role_sig), x_var in context.x_vars.items():
            # Group all X variables (worker-assignment) by their role within
            # a specific (shift, task) combination. Ignores worker_id here —
            # we only care about the aggregate count.
            x_vars_by_role[(s_id, t_id, role_sig)].append(x_var)

        # 2. Iterate through the domain structure (shifts -> tasks -> options)
        for shift in context.shifts:
            for task in shift.tasks:

                # Build a mapping: role_signature -> [(option_idx, headcount), ...]
                # This tells us: "For each role, which options need how many workers?"
                # Example: role ("Cook",) might need 2 workers under Option A and
                #          3 workers under Option B.
                role_requirements_map: Dict[Any, List[Tuple[int, int]]] = defaultdict(list)

                for opt_idx, option in enumerate(task.options):
                    for req in option.requirements:
                        # Reconstruct the exact same role signature that the
                        # solver engine used when creating X variables. The
                        # sorted() ensures order-independent matching.
                        s_key = tuple(sorted(req.required_skills.keys()))
                        role_sig = s_key

                        role_requirements_map[role_sig].append((opt_idx, req.count))

                # 3. Build the coverage equation for each distinct role.
                #
                # THE CORE LINKING CONSTRAINT between X and Y variables:
                #
                #   Sum(X_workers_assigned_to_role) == Sum(Y_option * headcount_for_role)
                #
                # In English: "The number of workers actually assigned to this
                # role must exactly match the headcount required by whichever
                # staffing option the solver selects."
                #
                # Example with 2 options for the "Cook" role:
                #   Option A (Y_0): needs 2 Cooks
                #   Option B (Y_1): needs 3 Cooks
                #   Constraint: X_alice + X_bob + X_cara == 2*Y_0 + 3*Y_1
                #   Since exactly one Y is 1 (structural constraint), this
                #   resolves to either "assign 2 cooks" or "assign 3 cooks".
                for role_sig, req_info in role_requirements_map.items():

                    # Left side: all X variables for workers that CAN fill this role
                    assigned_workers_vars = x_vars_by_role[(shift.shift_id, task.task_id, role_sig)]

                    # Right side: linear expression using Y vars and headcounts
                    required_count_expression = 0
                    for opt_idx, count in req_info:
                        y_key = (shift.shift_id, task.task_id, opt_idx)
                        # Y variable for this option (binary: 0 or 1)
                        y_var = context.y_vars.get(y_key)

                        if y_var is not None:
                            # count * Y_option: contributes headcount only if
                            # this option is the one selected by the solver.
                            required_count_expression += count * y_var

                    # Enforce exact coverage: assigned workers == required headcount.
                    # This is the equation that links the X and Y variable families.
                    context.solver.Add(sum(assigned_workers_vars) == required_count_expression)


class IntraShiftExclusivityConstraint(BaseConstraint):
    """Prevents a worker from performing multiple roles in the same shift.

    Also known as the "Superman Problem". A worker cannot be both a Waiter
    and a Cook in the exact same shift instance.
    """

    def __init__(self):
        """Initializes the exclusivity constraint."""
        super().__init__(
            name="intra_shift_exclusivity",
            constraint_type=ConstraintType.HARD,
            kind=ConstraintKind.STATIC
        )

    def apply(self, context: SolverContext) -> None:
        """Applies the exclusivity constraint.

        Uses the 'worker_shift_assignments' index from context which maps:
        (WorkerID, ShiftID) -> List of X variables assigned to that pair.
        """
        for (w_id, s_id), vars_in_shift in context.worker_shift_assignments.items():
            # If a worker has more than one potential assignment variable in a shift
            # (e.g., eligible for multiple roles), ensure they get at most 1.
            if len(vars_in_shift) > 1:
                # Formula: X_role1 + X_role2 + ... <= 1
                # In English: "A worker can fill at most one role per shift.
                # Alice cannot be both the Cook AND the Waiter in the same shift."
                context.solver.Add(sum(vars_in_shift) <= 1)


class OverlapPreventionConstraint(BaseConstraint):
    """Prevents a worker from being assigned to overlapping shifts.

    Ensures that if Shift A overlaps with Shift B, the worker is assigned
    to at most one of them.
    """

    def __init__(self):
        """Initializes the overlap prevention constraint."""
        super().__init__(
            name="overlap_prevention",
            constraint_type=ConstraintType.HARD,
            kind=ConstraintKind.STATIC
        )

    def apply(self, context: SolverContext) -> None:
        """Applies overlap logic using time-window analysis.

        Optimization:
            Iterates through pre-sorted assignments per worker. Uses an early
            break mechanism: if Shift B starts after Shift A ends, no subsequent
            shifts in the sorted list can overlap Shift A.
        """
        for w_id, assignment_list in context.worker_global_assignments.items():
            # assignment_list contains tuples of (Shift, X_Variable) — every
            # shift this worker is potentially eligible for across the schedule.

            # Sort by start time to enable an early-break optimization:
            # once Shift B starts after Shift A ends, no later shift can
            # overlap A either (because they start even later). O(N log N).
            assignment_list.sort(key=lambda x: x[0].time_window.start)

            num_assignments = len(assignment_list)
            for i in range(num_assignments):
                shift_a, var_a = assignment_list[i]

                for j in range(i + 1, num_assignments):
                    shift_b, var_b = assignment_list[j]

                    # Early break: Shift B starts after Shift A ends, so no
                    # subsequent shifts (sorted later) can overlap A.
                    if shift_b.time_window.start >= shift_a.time_window.end:
                        break

                    # Guard: only constrain distinct shifts (same-shift conflicts
                    # are handled by IntraShiftExclusivityConstraint).
                    if shift_a.shift_id != shift_b.shift_id:
                        if shift_a.time_window.overlaps(shift_b.time_window):
                            # Formula: X_shiftA + X_shiftB <= 1
                            # In English: "This worker cannot be assigned to two
                            # shifts that overlap in time. Pick at most one."
                            context.solver.Add(var_a + var_b <= 1)