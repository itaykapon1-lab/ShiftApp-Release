"""Optimization engine and orchestration for staff scheduling."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from ortools.linear_solver import pywraplp

from app.core.constants import (
    MAX_SOLVER_VARIABLES,
    SOLVER_RANDOM_SEED,
    SOLVER_TIMEOUT_MS,
)
from domain.shift_model import Shift
from domain.task_model import Requirement, Task
from domain.worker_model import Worker
from repositories.interfaces import IDataManager
from solver.constraints.base import SolverContext
from solver.constraints.registry import ConstraintRegistry
from solver.constraints.static_hard import (
    CoverageConstraint,
    IntraShiftExclusivityConstraint,
    OverlapPreventionConstraint,
)
from solver.constraints.static_soft import WorkerPreferencesConstraint
from solver.diagnostics_engine import DiagnosticsEngine
from solver.variable_builder import VariableBuilder

logger = logging.getLogger(__name__)

# --- MILP Type Aliases ---
# These composite-key types define the indexing scheme for the two families
# of binary decision variables in the scheduling MILP:
#   Y variables: "Which staffing option is selected for each task?"
#   X variables: "Which worker is assigned to which role?"

# A role signature is a sorted tuple of skill names that uniquely identifies
# a staffing role (e.g., ("Cook",) or ("Bartender", "Waiter")).
RoleSignature = Tuple[str, ...]

# Y variable key: (shift_id, task_id, option_index).
# Identifies which staffing option is selected for a given task in a shift.
YVarKey = Tuple[str, str, int]

# X variable key: (worker_id, shift_id, task_id, role_signature).
# Identifies a specific worker-to-role assignment within a task.
XVarKey = Tuple[str, str, str, RoleSignature]

# Maps each Y variable key to the list of Requirements (headcount + skills)
# for that staffing option — used by the CoverageConstraint to link X and Y.
TaskMetadataMap = Dict[YVarKey, List[Requirement]]

# Maps worker_id to all (Shift, X_variable) pairs across the entire schedule.
# Used by inter-shift constraints (overlap prevention, max hours, rest periods).
WorkerGlobalAssignments = Dict[str, List[Tuple[Shift, pywraplp.Variable]]]

# Maps (worker_id, shift_id) to X variables within that specific shift.
# Used by intra-shift constraints (exclusivity, mutual exclusion, co-location).
WorkerShiftAssignments = Dict[Tuple[str, str], List[pywraplp.Variable]]


class ShiftSolver:
    """Solves the staff scheduling problem with diagnostic capabilities."""

    def __init__(
        self,
        data_manager: IDataManager,
        constraint_registry: Optional[ConstraintRegistry] = None,
    ):
        self._data_manager = data_manager
        self._constraint_registry = constraint_registry or self._build_default_registry()

        # Backend selection cascade: prefer CBC (faster for MILPs), fall back to SCIP.
        # Both are LP/MILP solvers bundled with OR-Tools. If neither is available,
        # the solver cannot run at all.
        self._solver_id = "CBC"
        if not pywraplp.Solver.CreateSolver(self._solver_id):
            self._solver_id = "SCIP"

        if not pywraplp.Solver.CreateSolver(self._solver_id):
            raise RuntimeError("SCIP solver not available. Please install OR-Tools.")

        # The VariableBuilder constructs Y and X decision variables for the MILP.
        # It is decoupled from the engine to keep variable construction logic
        # separate from constraint application and result extraction.
        self._variable_builder = VariableBuilder(
            data_manager=self._data_manager,
            max_solver_variables=MAX_SOLVER_VARIABLES,
        )

        # The DiagnosticsEngine provides preflight checks (cheap data-only analysis)
        # and staged infeasibility diagnosis (incremental constraint testing).
        # It receives callbacks to build fresh contexts and query constraints,
        # avoiding a circular dependency with the engine.
        self._diagnostics = DiagnosticsEngine(
            data_manager=self._data_manager,
            build_context=self._build_optimization_context,
            get_hard_constraints=self._constraint_registry.get_hard_constraints,
            candidate_provider=self._variable_builder.get_candidates_for_requirement,
        )

        # Wire the diagnostic callback: when variable construction finds zero
        # eligible workers for a role, it triggers a detailed rejection analysis.
        self._variable_builder.zero_candidate_callback = (
            self._diagnostics.run_zero_candidate_diagnostic
        )
        logger.info("Solver ID: %s", self._solver_id)

    def _build_default_registry(self) -> ConstraintRegistry:
        """Builds the default constraint set when no custom registry is provided.

        The default set includes:
        - 3 HARD constraints (structural feasibility — the "physics" of scheduling):
          Coverage, IntraShiftExclusivity, OverlapPrevention
        - 1 SOFT constraint (optimization — worker happiness):
          WorkerPreferences
        """
        registry = ConstraintRegistry()
        registry.register(CoverageConstraint())
        registry.register(IntraShiftExclusivityConstraint())
        registry.register(OverlapPreventionConstraint())
        registry.register(WorkerPreferencesConstraint())
        return registry

    def _create_context_solver(self) -> pywraplp.Solver:
        """Creates and configures the base OR-Tools MILP solver instance.

        Configuration includes:
        - Time limit to prevent runaway solves on large problem instances.
        - Single-threaded execution for deterministic results across runs.
        - Random seed to ensure reproducible branching/cutting decisions.

        The seed strategy follows a 3-tier cascade:
        1. SetSeed() — direct API (not all backends support it).
        2. Backend-specific parameter strings (SCIP/CBC native config).
        3. Unsupported — log and proceed without determinism guarantee.
        """
        solver = pywraplp.Solver.CreateSolver(self._solver_id)
        if solver is None:
            raise RuntimeError(f"Configured solver backend '{self._solver_id}' is unavailable.")

        solver.SetTimeLimit(SOLVER_TIMEOUT_MS)

        # Single-threaded execution ensures deterministic variable branching
        # order. Multi-threaded solvers may explore branches in non-deterministic
        # order depending on OS thread scheduling.
        try:
            solver.SetNumThreads(1)
        except Exception:
            logger.debug("Solver backend %s does not support SetNumThreads(1)", self._solver_id)

        # --- Seed strategy cascade ---
        # Deterministic solving requires controlling the random seed that the
        # solver backend uses for tie-breaking, variable permutation, and
        # cut selection. Different backends expose this differently.
        seed_strategy = "unsupported"
        if hasattr(solver, "SetSeed"):
            # Tier 1: Direct API (preferred — cleanest interface).
            try:
                solver.SetSeed(SOLVER_RANDOM_SEED)
                seed_strategy = "SetSeed"
            except Exception:
                logger.warning(
                    "Solver backend %s rejected SetSeed(%d)",
                    self._solver_id,
                    SOLVER_RANDOM_SEED,
                    exc_info=True,
                )
        else:
            # Tier 2: Backend-specific parameter strings (SCIP/CBC native config).
            params = self._get_seed_parameter_string()
            if params:
                applied = solver.SetSolverSpecificParametersAsString(params)
                if applied:
                    seed_strategy = "SetSolverSpecificParametersAsString"
                else:
                    # Tier 3: Backend silently rejected parameters — determinism
                    # is NOT guaranteed. This is operationally significant.
                    seed_strategy = "parameters_not_applied"
                    logger.warning(
                        "Solver backend %s did not accept seed parameters; "
                        "deterministic solving is NOT guaranteed.",
                        self._solver_id,
                    )

        logger.info(
            "Configured solver backend=%s timeout_ms=%d seed=%d strategy=%s",
            self._solver_id,
            SOLVER_TIMEOUT_MS,
            SOLVER_RANDOM_SEED,
            seed_strategy,
        )
        return solver

    def _get_seed_parameter_string(self) -> str:
        """Returns backend-specific parameter strings for seeding randomization.

        SCIP uses three parameters:
        - randomseedshift: offsets the internal RNG seed.
        - permutationseed: controls variable/constraint permutation order.
        - permutevars: enables variable permutation (required for seed to matter).

        CBC uses a single randomSeed parameter.
        """
        if self._solver_id == "SCIP":
            return (
                f"randomization/randomseedshift = {SOLVER_RANDOM_SEED}\n"
                f"randomization/permutationseed = {SOLVER_RANDOM_SEED}\n"
                "randomization/permutevars = TRUE\n"
            )
        if self._solver_id == "CBC":
            return f"randomSeed={SOLVER_RANDOM_SEED}\n"
        return ""

    def _initialize_context_containers(
        self,
    ) -> Tuple[
        Dict[YVarKey, pywraplp.Variable],
        Dict[XVarKey, pywraplp.Variable],
        WorkerGlobalAssignments,
        WorkerShiftAssignments,
        TaskMetadataMap,
    ]:
        """Initializes the mutable containers that back the solver context.

        These containers are populated during variable construction and then
        passed into the SolverContext for use by all constraints. They provide
        multiple indexing strategies over the same set of decision variables,
        enabling O(1) lookups during constraint application.
        """
        # Primary Y variable store: (shift, task, option) -> binary variable.
        y_vars: Dict[YVarKey, pywraplp.Variable] = {}

        # Primary X variable store: (worker, shift, task, role) -> binary variable.
        x_vars: Dict[XVarKey, pywraplp.Variable] = {}

        # Secondary index: worker_id -> [(Shift, X_var), ...] across ALL shifts.
        # Used by inter-shift constraints (overlap, max hours, rest periods).
        worker_global_assignments: WorkerGlobalAssignments = defaultdict(list)

        # Secondary index: (worker_id, shift_id) -> [X_var, ...] within ONE shift.
        # Used by intra-shift constraints (exclusivity, mutual exclusion).
        worker_shift_assignments: WorkerShiftAssignments = defaultdict(list)

        # Maps each Y variable key to the list of Requirements for that option.
        # Used by CoverageConstraint to link X (assignments) with Y (options).
        task_metadata: TaskMetadataMap = defaultdict(list)

        return (
            y_vars,
            x_vars,
            worker_global_assignments,
            worker_shift_assignments,
            task_metadata,
        )

    def _build_optimization_context(self) -> SolverContext:
        """Constructs the complete MILP model: solver instance, decision variables, and indexes.

        This is the "model construction" phase of the solve pipeline. It:
        1. Creates a configured solver instance (backend, timeout, seed).
        2. Loads all domain data (shifts, workers) from the data manager.
        3. Initializes empty containers for variables and indexes.
        4. Delegates to VariableBuilder to populate Y vars, X vars, and indexes.
        5. Assembles everything into a SolverContext for constraint application.

        After this method returns, the context contains the full variable model
        but NO constraints — those are applied separately by the ConstraintRegistry.
        """
        solver = self._create_context_solver()

        # Load the complete domain snapshot for this session.
        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()
        logger.info("Shifts: %d", len(shifts))
        logger.info("Workers: %d", len(workers))

        (
            y_vars,
            x_vars,
            worker_global_assignments,
            worker_shift_assignments,
            task_metadata,
        ) = self._initialize_context_containers()

        # Refresh data manager's internal lookup indexes (skill/availability caches)
        # before variable construction, which performs eligibility queries.
        self._data_manager.refresh_indices()

        # Build all Y and X decision variables. This also applies the structural
        # constraint sum(Y_options) == 1 per task (exactly one option must be selected).
        # The circuit breaker inside will raise ValueError if the estimated variable
        # count exceeds MAX_SOLVER_VARIABLES.
        expected_vars = self._variable_builder.build_all_task_variables(
            solver=solver,
            shifts=shifts,
            y_vars=y_vars,
            x_vars=x_vars,
            worker_global_assignments=worker_global_assignments,
            worker_shift_assignments=worker_shift_assignments,
            task_metadata=task_metadata,
        )
        logger.warning("Estimated variable count before solve: %d", expected_vars)

        # Package all state into the shared context that constraints will operate on.
        return SolverContext(
            solver=solver,
            x_vars=x_vars,
            y_vars=y_vars,
            shifts=shifts,
            workers=workers,
            worker_shift_assignments=worker_shift_assignments,
            worker_global_assignments=worker_global_assignments,
            task_metadata=task_metadata,
        )

    def _build_task_variables(
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
        self._variable_builder.build_task_variables(
            solver=solver,
            shift=shift,
            task=task,
            y_vars=y_vars,
            x_vars=x_vars,
            worker_global_assignments=worker_global_assignments,
            worker_shift_assignments=worker_shift_assignments,
            task_metadata=task_metadata,
        )

    def _create_option_selection_variables(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        y_vars: Dict[YVarKey, pywraplp.Variable],
        task_metadata: TaskMetadataMap,
    ) -> List[pywraplp.Variable]:
        return self._variable_builder.create_option_selection_variables(
            solver=solver,
            shift=shift,
            task=task,
            y_vars=y_vars,
            task_metadata=task_metadata,
        )

    def _create_worker_assignment_variables(
        self,
        solver: pywraplp.Solver,
        shift: Shift,
        task: Task,
        x_vars: Dict[XVarKey, pywraplp.Variable],
        worker_global_assignments: WorkerGlobalAssignments,
        worker_shift_assignments: WorkerShiftAssignments,
    ) -> None:
        self._variable_builder.create_worker_assignment_variables(
            solver=solver,
            shift=shift,
            task=task,
            x_vars=x_vars,
            worker_global_assignments=worker_global_assignments,
            worker_shift_assignments=worker_shift_assignments,
        )

    def _get_candidates_for_requirement(
        self,
        shift: Shift,
        req: Requirement,
    ) -> List[Worker]:
        return self._variable_builder.get_candidates_for_requirement(shift, req)

    def _run_zero_candidate_diagnostic(
        self,
        shift: Shift,
        req: Requirement,
    ) -> None:
        self._diagnostics.run_zero_candidate_diagnostic(shift, req)

    def _create_assignment_variables_for_candidates(
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
        self._variable_builder.create_assignment_variables_for_candidates(
            solver=solver,
            shift=shift,
            task=task,
            role_sig=role_sig,
            candidates=candidates,
            x_vars=x_vars,
            worker_global_assignments=worker_global_assignments,
            worker_shift_assignments=worker_shift_assignments,
        )

    def _audit_objective_coefficients(self, context: SolverContext) -> Tuple[int, float]:
        """Counts non-zero X coefficients in the objective for debug auditing.

        This audit answers the question: "Did the constraint system successfully
        inject preference scores into the objective function?" If non_zero_coeffs
        is 0 when preferences exist, it indicates a wiring problem in the
        WorkerPreferencesConstraint.

        Returns:
            Tuple of (count of X vars with non-zero coefficients,
                      sum of absolute coefficient values as theoretical max score).
        """
        objective = context.solver.Objective()
        non_zero_coeffs = 0
        total_score_potential = 0.0

        for x_var in context.x_vars.values():
            coeff = objective.GetCoefficient(x_var)
            if coeff != 0:
                non_zero_coeffs += 1
                # Absolute value because penalties are negative and rewards
                # are positive — we want the total magnitude of possible impact.
                total_score_potential += abs(coeff)

        return non_zero_coeffs, total_score_potential

    def _populate_success_result(
        self,
        context: SolverContext,
        result_data: Dict[str, Any],
        status: int,
    ) -> None:
        """Populates the result payload for feasible or optimal solves."""
        result_data["status"] = "Optimal" if status == pywraplp.Solver.OPTIMAL else "Feasible"
        result_data["objective_value"] = context.solver.Objective().Value()
        result_data["violations"] = self._constraint_registry.get_violations(context)
        result_data["penalty_breakdown"] = self._constraint_registry.get_penalty_breakdown(
            context
        )
        self._extract_assignments(context, result_data)

    def solve(self) -> Dict[str, Any]:
        """Executes the full solve pipeline and returns the scheduling result.

        Pipeline stages:
        1. **Preflight** — cheap data-only checks (skill gaps, availability, headcount).
           Returns early with diagnosis if the problem is structurally doomed.
        2. **Model construction** — builds Y/X variables and structural constraints.
        3. **Constraint application** — applies hard then soft constraints via registry.
        4. **Objective audit** — counts non-zero coefficients for debug telemetry.
        5. **Solve** — invokes the MILP backend (maximize the objective function).
        6. **Result extraction** — reads solution values into a human-readable dict.
        """
        # --- Stage 1: Preflight checks (no solver allocation needed) ---
        # These are O(shifts * workers) data scans that catch obviously doomed
        # problems before we spend CPU building and solving the MILP model.
        preflight_message = self._run_preflight_checks()
        if preflight_message:
            logger.warning("Preflight check failed: %s", preflight_message[:200])
            return {
                "status": "Infeasible",
                "assignments": [],
                "objective_value": 0,
                "violations": {},
                "penalty_breakdown": {},
                "theoretical_max_score": 0,
                "diagnosis_message": preflight_message,
            }

        # --- Stage 2: Model construction ---
        # Creates the solver instance, builds Y (option selection) and X (worker
        # assignment) binary variables, and populates all lookup indexes.
        context = self._build_optimization_context()
        logger.info("Context built - applying constraints")

        # --- Stage 3: Constraint application ---
        # Hard constraints (coverage, exclusivity, overlap) are applied first to
        # define the feasible region. Soft constraints (preferences, max hours,
        # rest periods) then add penalty/reward coefficients to the objective.
        self._constraint_registry.apply_all(context)
        logger.info("Constraints applied")

        # --- Stage 4: Objective audit ---
        # Count how many X variables have non-zero objective coefficients and the
        # total potential score. This helps operators understand whether preference
        # data is flowing correctly into the model.
        non_zero_coeffs, total_score_potential = self._audit_objective_coefficients(context)
        logger.debug(
            "Objective: %d vars with coefficients, total potential %s",
            non_zero_coeffs,
            total_score_potential,
        )

        # --- Stage 5: Solve ---
        # Set the optimization direction to MAXIMIZE (we want the highest total
        # preference/reward score minus penalties). Then invoke the MILP backend.
        context.solver.Objective().SetMaximization()
        var_count = context.solver.NumVariables()
        constraint_count = context.solver.NumConstraints()
        logger.info(
            "Starting solve backend=%s vars=%d constraints=%d",
            self._solver_id,
            var_count,
            constraint_count,
        )
        solve_started = time.monotonic()
        status = context.solver.Solve()
        solve_duration = time.monotonic() - solve_started
        logger.info(
            "Solve finished backend=%s status=%s duration=%.3fs vars=%d constraints=%d",
            self._solver_id,
            self._status_name(status),
            solve_duration,
            var_count,
            constraint_count,
        )

        # --- Stage 6: Result extraction ---
        result_data = {
            "status": "Unknown",
            "assignments": [],
            "objective_value": 0,
            "violations": {},
            "penalty_breakdown": {},
            "theoretical_max_score": total_score_potential,
        }

        if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
            # Extract concrete worker-to-shift assignments from solved X variables.
            self._populate_success_result(context, result_data, status)
        else:
            # The MILP has no feasible solution — all hard constraints cannot be
            # simultaneously satisfied. Diagnosis is available via diagnose_infeasibility().
            result_data["status"] = "Infeasible"

        return result_data

    def _run_preflight_checks(self) -> Optional[str]:
        return self._diagnostics.run_preflight_checks()

    def _diagnose_base_model_failure(self) -> Optional[str]:
        return self._diagnostics.diagnose_base_model_failure()

    def _diagnose_individual_hard_constraints(
        self,
        hard_constraints: List[Any],
    ) -> Optional[str]:
        return self._diagnostics.diagnose_individual_hard_constraints(hard_constraints)

    def _diagnose_hard_constraint_conflicts(
        self,
        hard_constraints: List[Any],
    ) -> Optional[str]:
        return self._diagnostics.diagnose_hard_constraint_conflicts(hard_constraints)

    def diagnose_infeasibility(self) -> str:
        return self._diagnostics.diagnose_infeasibility()

    def _check_skill_gaps(self) -> Optional[str]:
        return self._diagnostics.check_skill_gaps()

    def _check_availability_gaps(self) -> Optional[str]:
        return self._diagnostics.check_availability_gaps()

    def _check_headcount_gaps(self) -> Optional[str]:
        return self._diagnostics.check_headcount_gaps()

    def _get_friendly_error(self, name: str) -> str:
        return self._diagnostics.get_friendly_error(name)

    def _get_enabled_worker_preferences_constraint(
        self,
    ) -> Optional[WorkerPreferencesConstraint]:
        """Returns the enabled worker-preferences constraint from the registry."""
        return next(
            (
                c
                for c in self._constraint_registry._constraints
                if isinstance(c, WorkerPreferencesConstraint) and c.enabled
            ),
            None,
        )

    def _resolve_task_name(self, shift: Optional[Shift], task_id: str) -> str:
        """Looks up the task name inside a resolved shift."""
        task_name = "Unknown"
        if shift:
            for task in shift.tasks:
                if task.task_id == task_id:
                    task_name = task.name
                    break
        return task_name

    def _calculate_assignment_score(
        self,
        worker: Worker,
        shift: Shift,
        pref_constraint: Optional[WorkerPreferencesConstraint],
    ) -> Tuple[int, str]:
        """Calculates per-assignment score breakdown for result explainability."""
        current_score = 0
        breakdown_reasons: List[str] = []

        if pref_constraint:
            raw_pref_score = worker.calculate_preference_score(shift.time_window)

            if raw_pref_score > 0:
                current_score += pref_constraint.preference_reward
                breakdown_reasons.append(f"+{pref_constraint.preference_reward} (Pref)")
            elif raw_pref_score < 0:
                current_score += pref_constraint.preference_penalty
                breakdown_reasons.append(f"{pref_constraint.preference_penalty} (Avoid)")

        breakdown_str = ", ".join(breakdown_reasons) if breakdown_reasons else "-"
        return current_score, breakdown_str

    def _extract_assignments(self, context: SolverContext, result_data: Dict[str, Any]) -> None:
        """Extracts solved X variable values into a human-readable assignment list.

        Iterates over all X (worker-assignment) variables and collects those
        where the solver assigned the worker (solution_value > 0.5). For each
        active assignment, resolves the worker/shift/task names and computes
        per-assignment preference scores for result explainability.
        """
        pref_constraint = self._get_enabled_worker_preferences_constraint()

        for key, x_var in context.x_vars.items():
            # Binary variable rounding: X variables are IntVar(0, 1). Due to
            # floating-point representation, the solution value may not be exactly
            # 0 or 1. Threshold at 0.5 to determine if the worker IS assigned.
            if x_var.solution_value() > 0.5:
                w_id, s_id, t_id, role_sig = key

                worker = self._data_manager.get_worker(w_id)
                shift = self._data_manager.get_shift(s_id)
                task_name = self._resolve_task_name(shift, t_id)

                if worker and shift:
                    current_score, breakdown_str = self._calculate_assignment_score(
                        worker=worker,
                        shift=shift,
                        pref_constraint=pref_constraint,
                    )

                    skills_list = list(role_sig)
                    role_str = f"Skills: {skills_list}"

                    result_data["assignments"].append(
                        {
                            "worker_name": worker.name,
                            "worker_id": worker.worker_id,
                            "shift_name": shift.name,
                            "shift_id": shift.shift_id,
                            "time": str(shift.time_window),
                            "task": task_name,
                            "role_details": role_str,
                            "score": current_score,
                            "score_breakdown": breakdown_str,
                        }
                    )

    def _status_name(self, status: int) -> str:
        if status == pywraplp.Solver.OPTIMAL:
            return "OPTIMAL"
        if status == pywraplp.Solver.FEASIBLE:
            return "FEASIBLE"
        if status == pywraplp.Solver.INFEASIBLE:
            return "INFEASIBLE"
        if status == pywraplp.Solver.ABNORMAL:
            return "ABNORMAL"
        if status == pywraplp.Solver.NOT_SOLVED:
            return "NOT_SOLVED"
        if status == pywraplp.Solver.UNBOUNDED:
            return "UNBOUNDED"
        return f"STATUS_{status}"
