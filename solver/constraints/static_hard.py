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
        # 1. Pre-index X variables for O(1) lookup
        # Key: (shift_id, task_id, role_signature) -> Value: List[x_var]
        x_vars_by_role: Dict[Tuple[str, str, Any], List[pywraplp.Variable]] = defaultdict(list)

        for (w_id, s_id, t_id, role_sig), x_var in context.x_vars.items():
            x_vars_by_role[(s_id, t_id, role_sig)].append(x_var)

        # 2. Iterate through the domain structure
        for shift in context.shifts:
            for task in shift.tasks:

                # Map distinct roles to their requirements across different options
                # Key: RoleSignature -> Value: List of (Option_Index, Required_Count)
                role_requirements_map: Dict[Any, List[Tuple[int, int]]] = defaultdict(list)

                for opt_idx, option in enumerate(task.options):
                    for req in option.requirements:
                        # Reconstruct the role signature exactly as the Solver engine did
                        # to match the keys in x_vars.
                        s_key = tuple(sorted(req.required_skills.keys()))
                        role_sig = s_key

                        role_requirements_map[role_sig].append((opt_idx, req.count))

                # 3. Build the constraint equation for each role
                for role_sig, req_info in role_requirements_map.items():

                    # Left side: Sum of workers assigned to this role (X variables)
                    assigned_workers_vars = x_vars_by_role[(shift.shift_id, task.task_id, role_sig)]

                    # Right side: Sum of (Count * Option_Selected_Y)
                    required_count_expression = 0
                    for opt_idx, count in req_info:
                        y_key = (shift.shift_id, task.task_id, opt_idx)
                        y_var = context.y_vars.get(y_key)

                        if y_var is not None:
                            required_count_expression += count * y_var

                    # Apply: Sum(X) == Expression(Y)
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
            # assignment_list contains tuples of (Shift, Variable)

            # Sort by start time to enable O(N*logN) check instead of O(N^2)
            assignment_list.sort(key=lambda x: x[0].time_window.start)

            num_assignments = len(assignment_list)
            for i in range(num_assignments):
                shift_a, var_a = assignment_list[i]

                for j in range(i + 1, num_assignments):
                    shift_b, var_b = assignment_list[j]

                    # Optimization: Break inner loop if no further overlaps are possible
                    if shift_b.time_window.start >= shift_a.time_window.end:
                        break

                    # Check for actual overlap (redundant if using strictly sorted logic above,
                    # but explicit check handles edge cases like 0-minute overlaps if defined).
                    if shift_a.shift_id != shift_b.shift_id:
                        if shift_a.time_window.overlaps(shift_b.time_window):
                            # Constraint: Can assign A OR B (or neither), but not both.
                            context.solver.Add(var_a + var_b <= 1)