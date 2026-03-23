"""Variable construction helpers for the MILP scheduling model.

This module is responsible for creating the two families of binary decision
variables that form the core of the shift-scheduling MILP formulation:

  Y variables ("Option Selection"):
    One binary variable per (shift, task, option). Exactly one Y per task
    must be 1 (enforced by the structural constraint sum(Y) == 1).
    Represents: "Which staffing configuration is selected for this task?"

  X variables ("Worker Assignment"):
    One binary variable per (worker, shift, task, role). Each X = 1 means
    "this worker is assigned to this role in this task during this shift."
    These are linked to Y variables via the CoverageConstraint.

The builder also maintains secondary indexes (worker_global_assignments,
worker_shift_assignments) that allow constraints to query assignments
efficiently without scanning the full x_vars dictionary.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ortools.linear_solver import pywraplp

from app.core.constants import MAX_SOLVER_VARIABLES
from domain.shift_model import Shift
from domain.task_model import Requirement, Task
from domain.worker_model import Worker
from repositories.interfaces import IDataManager

logger = logging.getLogger(__name__)

# --- MILP Type Aliases (mirrored from solver_engine.py) ---
# See solver_engine.py for detailed documentation on each type.
RoleSignature = Tuple[str, ...]
YVarKey = Tuple[str, str, int]
XVarKey = Tuple[str, str, str, RoleSignature]
TaskMetadataMap = Dict[YVarKey, List[Requirement]]
WorkerGlobalAssignments = Dict[str, List[Tuple[Shift, pywraplp.Variable]]]
WorkerShiftAssignments = Dict[Tuple[str, str], List[pywraplp.Variable]]

# Callback signature for the zero-candidate diagnostic hook.
# Invoked when no eligible workers exist for a requirement, allowing the
# DiagnosticsEngine to log detailed rejection analysis.
ZeroCandidateCallback = Callable[[Shift, Requirement], None]


class VariableBuilder:
    """Builds Y/X variables and supporting indexes for the solver context."""

    def __init__(
        self,
        data_manager: IDataManager,
        max_solver_variables: int = MAX_SOLVER_VARIABLES,
        zero_candidate_callback: Optional[ZeroCandidateCallback] = None,
    ) -> None:
        self._data_manager = data_manager
        self._max_solver_variables = max_solver_variables
        self.zero_candidate_callback = zero_candidate_callback

    def build_all_task_variables(
        self,
        solver: pywraplp.Solver,
        shifts: Sequence[Shift],
        y_vars: Dict[YVarKey, pywraplp.Variable],
        x_vars: Dict[XVarKey, pywraplp.Variable],
        worker_global_assignments: WorkerGlobalAssignments,
        worker_shift_assignments: WorkerShiftAssignments,
        task_metadata: TaskMetadataMap,
    ) -> int:
        """Builds all Y and X decision variables for every task in every shift.

        Runs an in-stream circuit breaker that checks the total variable count
        during the build. If it exceeds MAX_SOLVER_VARIABLES, the build is aborted
        to prevent the solver from consuming excessive memory on pathologically
        large inputs.
        """
        # --- Main build loop: iterate shifts -> tasks -> variables ---
        for shift in shifts:
            logger.debug("Shift '%s' has %d tasks", shift.name, len(shift.tasks))
            for task in shift.tasks:
                self.build_task_variables(
                    solver=solver,
                    shift=shift,
                    task=task,
                    y_vars=y_vars,
                    x_vars=x_vars,
                    worker_global_assignments=worker_global_assignments,
                    worker_shift_assignments=worker_shift_assignments,
                    task_metadata=task_metadata,
                )
                
                # --- In-stream Circuit Breaker ---
                # Raise immediately if variable count breaches limit mid-build.
                current_vars = len(y_vars) + len(x_vars)
                if current_vars >= self._max_solver_variables:
                    raise ValueError(
                        "Solver circuit breaker triggered: estimated variable count "
                        f"{current_vars} meets or exceeds limit {self._max_solver_variables}."
                    )
                    
        return len(y_vars) + len(x_vars)



    def build_task_variables(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        y_vars: Dict[YVarKey, pywraplp.Variable],
        x_vars: Dict[XVarKey, pywraplp.Variable],
        worker_global_assignments: WorkerGlobalAssignments,
        worker_shift_assignments: WorkerShiftAssignments,
        task_metadata: TaskMetadataMap,
    ) -> None:
        """Builds all decision variables for a single task and applies the option exclusivity constraint.

        This method creates two sets of variables for the task:
        1. Y variables (option selection) — one per staffing option.
        2. X variables (worker assignment) — one per eligible worker per unique role.

        It also enforces the fundamental structural constraint: exactly one
        staffing option must be selected per task.
        """
        # Step 1: Create one Y variable per staffing option for this task.
        # Also records each option's requirements in task_metadata for use
        # by the CoverageConstraint when linking X and Y variables.
        task_option_vars = self.create_option_selection_variables(
            solver=solver,
            shift=shift,
            task=task,
            y_vars=y_vars,
            task_metadata=task_metadata,
        )

        # STRUCTURAL CONSTRAINT: Exactly one staffing option must be selected.
        # Formula: Y_option0 + Y_option1 + ... + Y_optionN == 1
        # In English: "The solver must choose exactly one staffing configuration
        # for this task. It cannot skip the task or use multiple options."
        # This is the constraint that makes Y variables mutually exclusive,
        # ensuring the CoverageConstraint resolves to a single headcount target.
        solver.Add(sum(task_option_vars) == 1)

        # Step 2: Create X variables for each eligible worker for each unique role.
        # Roles are deduplicated across options (same skill set = same X variable).
        self.create_worker_assignment_variables(
            solver=solver,
            shift=shift,
            task=task,
            x_vars=x_vars,
            worker_global_assignments=worker_global_assignments,
            worker_shift_assignments=worker_shift_assignments,
        )

    def create_option_selection_variables(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        y_vars: Dict[YVarKey, pywraplp.Variable],
        task_metadata: TaskMetadataMap,
    ) -> List[pywraplp.Variable]:
        """Creates one Y (option-selection) binary variable per staffing option.

        Each Y variable represents: "Is this staffing option selected for this task?"
        The variables are indexed by the composite key (shift_id, task_id, option_index)
        in the y_vars dictionary for O(1) lookup by constraints.

        If an option has a non-zero preference_score (set by the user in the task
        configuration), it is added as an objective coefficient on the Y variable.
        This allows the solver to prefer certain staffing configurations over others.

        Returns:
            List of Y variables for this task (one per option), to be used in the
            sum(Y) == 1 structural constraint.
        """
        task_option_vars = []
        for opt_idx, option in enumerate(task.options):
            # Create a binary (0/1) variable: Y=1 means this option is selected.
            y_name = f"Y_{shift.shift_id}_{task.task_id}_{opt_idx}"
            y_var = solver.IntVar(0, 1, y_name)

            # Register in the Y variable dictionary with its composite key.
            y_vars[(shift.shift_id, task.task_id, opt_idx)] = y_var
            task_option_vars.append(y_var)

            # If this option has an inherent preference score (e.g., the user
            # prefers Option A over Option B), inject it into the objective.
            # This coefficient is additive with any later TaskOptionPriority penalty.
            if option.preference_score != 0:
                solver.Objective().SetCoefficient(y_var, option.preference_score)

            # Store the option's requirements (headcount + skills per role) so the
            # CoverageConstraint can build the linking equation: sum(X) == sum(Y * count).
            task_metadata[(shift.shift_id, task.task_id, opt_idx)] = option.requirements

        return task_option_vars

    def create_worker_assignment_variables(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        x_vars: Dict[XVarKey, pywraplp.Variable],
        worker_global_assignments: WorkerGlobalAssignments,
        worker_shift_assignments: WorkerShiftAssignments,
    ) -> None:
        """Creates X (worker-assignment) variables for each distinct role in a task.

        Key design decision: roles are DEDUPLICATED across options using the
        role_signature (sorted tuple of skill names). If Option A needs 2 Cooks
        and Option B needs 3 Cooks, the X variables for "Cook" are created ONCE
        and shared by both options. The CoverageConstraint then uses Y variables
        to determine the required headcount.

        This deduplication is essential for correctness — without it, the coverage
        constraint would see different X variable pools for the same role under
        different options, breaking the linking equation.
        """
        # Track which role signatures we've already processed for this task.
        # A role_sig like ("Cook",) or ("Bartender", "Waiter") uniquely identifies
        # the skill set for a role, regardless of which option defines it.
        processed_roles = set()

        for option in task.options:
            for req in option.requirements:
                # Sorted tuple ensures order-independent matching:
                # {"Cook", "Bartender"} == {"Bartender", "Cook"} after sorting.
                role_sig = tuple(sorted(req.required_skills.keys()))

                # Skip if we already created X variables for this role in this task.
                if role_sig in processed_roles:
                    continue
                processed_roles.add(role_sig)

                # Find all workers eligible for this role (available + skilled).
                candidates = self.get_candidates_for_requirement(shift, req)

                # Create one X variable per eligible worker for this role.
                self.create_assignment_variables_for_candidates(
                    solver=solver,
                    shift=shift,
                    task=task,
                    role_sig=role_sig,
                    candidates=candidates,
                    x_vars=x_vars,
                    worker_global_assignments=worker_global_assignments,
                    worker_shift_assignments=worker_shift_assignments,
                )

    def get_candidates_for_requirement(
        self,
        shift: Shift,
        req: Requirement,
    ) -> List[Worker]:
        """Retrieves eligible workers for one requirement and logs diagnostics."""
        logger.debug("Candidate search: Shift=%s, Skills=%s", shift.name, req.required_skills)

        candidates = self.lookup_candidates(shift, req)

        logger.debug("  Found %d eligible candidates", len(candidates))

        if len(candidates) == 0:
            logger.warning("   NO CANDIDATES FOUND! Performing manual diagnostic...")
            if self.zero_candidate_callback is not None:
                self.zero_candidate_callback(shift, req)

        return candidates

    def lookup_candidates(
        self,
        shift: Shift,
        req: Requirement,
    ) -> List[Worker]:
        """Returns eligible workers without emitting diagnostics side effects.

        Eligibility is determined by the data manager, which checks:
        1. Availability: worker has a time window covering the entire shift.
        2. Skills: worker possesses all required skills at the required levels.

        This is the "quiet" lookup used by the circuit breaker estimator.
        For the diagnostic-enabled version, see get_candidates_for_requirement().
        """
        return self._data_manager.get_eligible_workers(
            time_window=shift.time_window,
            required_skills=req.required_skills,
        )

    def create_assignment_variables_for_candidates(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        role_sig: RoleSignature,
        candidates: List[Worker],
        x_vars: Dict[XVarKey, pywraplp.Variable],
        worker_global_assignments: WorkerGlobalAssignments,
        worker_shift_assignments: WorkerShiftAssignments,
    ) -> None:
        """Creates one X (binary assignment) variable per eligible worker for a role.

        Each X variable represents: "Is this worker assigned to this role in this
        task during this shift?" The variable is indexed by the 4-tuple composite
        key (worker_id, shift_id, task_id, role_signature) in x_vars.

        In addition to the primary x_vars store, each new variable is registered
        in two secondary indexes to support fast constraint lookups:
        - worker_global_assignments: for inter-shift constraints (overlap, max hours).
        - worker_shift_assignments: for intra-shift constraints (exclusivity, bans).
        """
        for worker in candidates:
            # Composite key uniquely identifies this worker-role-task-shift combination.
            key = (worker.worker_id, shift.shift_id, task.task_id, role_sig)

            # Guard against duplicate variable creation. This can happen if the
            # same worker is eligible for the same role through different query
            # paths (e.g., multiple options with the same role signature).
            if key not in x_vars:
                # Create a binary (0/1) variable: X=1 means worker is assigned.
                x_name = f"X_{worker.worker_id}_{shift.shift_id}_{task.task_id}_{hash(role_sig)}"
                x_var = solver.IntVar(0, 1, x_name)
                x_vars[key] = x_var

                # Populate secondary index: all assignments for this worker across
                # the entire schedule (used by OverlapPrevention, MaxHours, etc.).
                worker_global_assignments[worker.worker_id].append((shift, x_var))

                # Populate secondary index: all assignments for this worker within
                # this specific shift (used by IntraShiftExclusivity, MutualExclusion).
                worker_shift_assignments[(worker.worker_id, shift.shift_id)].append(x_var)


