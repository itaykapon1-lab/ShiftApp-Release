"""
Optimization Engine Module.

Refactored to support Diagnostic capabilities and correct Metadata flow.
"""
import logging
import sys
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict
from ortools.linear_solver import pywraplp

# Domain & Interface Imports
from repositories.interfaces import IDataManager
from domain.shift_model import Shift
from domain.task_model import Task
from domain.worker_model import Worker

# Constraint System Imports
from solver.constraints.base import SolverContext
from solver.constraints.registry import ConstraintRegistry
from solver.constraints.static_hard import (
    CoverageConstraint,
    IntraShiftExclusivityConstraint,
    OverlapPreventionConstraint
)
from solver.constraints.static_soft import WorkerPreferencesConstraint
from app.core.constants import SOLVER_TIMEOUT_MS
import logging
logger = logging.getLogger(__name__)

class ShiftSolver:
    """Solves the staff scheduling problem with diagnostic capabilities."""

    def __init__(self,
                 data_manager: IDataManager,
                 constraint_registry: Optional[ConstraintRegistry] = None):
        self._data_manager = data_manager
        self._constraint_registry = constraint_registry or self._build_default_registry()
        self._solver_id = 'CBC'
        if not pywraplp.Solver.CreateSolver(self._solver_id):
            self._solver_id = 'SCIP'

        if not pywraplp.Solver.CreateSolver(self._solver_id):
            raise RuntimeError("SCIP solver not available. Please install OR-Tools.")
        logger.info(f"Solver ID: {self._solver_id}")

    def _build_default_registry(self) -> ConstraintRegistry:
        registry = ConstraintRegistry()
        registry.register(CoverageConstraint())
        registry.register(IntraShiftExclusivityConstraint())
        registry.register(OverlapPreventionConstraint())
        registry.register(WorkerPreferencesConstraint())
        return registry

    def _build_optimization_context(self) -> SolverContext:
        """
        Constructs the mathematical model (Variables & Scope) WITHOUT applying constraints.
        This allows us to reuse the model structure for both solving and diagnostics.
        """
        solver = pywraplp.Solver.CreateSolver('SCIP')
        solver.SetTimeLimit(SOLVER_TIMEOUT_MS)  # 5-minute hard safety limit

        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()
        logger.info(f"Shifts: {len(shifts)}")
        logger.info(f"Workers: {len(workers)}")

        # Variables Containers
        y_vars: Dict[Tuple[str, str, int], pywraplp.Variable] = {}
        x_vars: Dict[Tuple[str, str, str, Any], pywraplp.Variable] = {}

        # Indices for Constraints
        worker_global_assignments = defaultdict(list)
        worker_shift_assignments = defaultdict(list)

        # Metadata map: (shift_id, task_id, option_idx) -> List[Requirement]
        # Critical for the CoverageConstraint to know "How many people needed?"
        task_metadata: Dict[Tuple[str, str, int], List[Any]] = defaultdict(list)
        self._data_manager.refresh_indices()
        logger.info(f"Shifts2: {len(shifts)}")

        # --- Variable Creation Phase ---

        for shift in shifts:
            logger.debug(f"Shift '{shift.name}' has {len(shift.tasks)} tasks")
            for task in shift.tasks:

                # A. Option Selection Variables (Y)
                task_option_vars = []
                for opt_idx, option in enumerate(task.options):
                    y_name = f"Y_{shift.shift_id}_{task.task_id}_{opt_idx}"
                    y_var = solver.IntVar(0, 1, y_name)
                    y_vars[(shift.shift_id, task.task_id, opt_idx)] = y_var
                    task_option_vars.append(y_var)

                    # Objective: Option Preference
                    if option.preference_score != 0:
                        solver.Objective().SetCoefficient(y_var, option.preference_score)

                    # Store metadata so CoverageConstraint can access it later
                    task_metadata[(shift.shift_id, task.task_id, opt_idx)] = option.requirements

                # Structural Constraint: Exactly one option must be chosen per task.
                # This is fundamental to the problem definition, so we keep it here.
                solver.Add(sum(task_option_vars) == 1)

                # B. Worker Assignment Variables (X)
                # We iterate options -> requirements to find all possible roles needed
                processed_roles = set()

                for option in task.options:
                    for req in option.requirements:
                        # Create generic Role Signature (using skill names as strings)
                        s_key = tuple(sorted(req.required_skills.keys()))
                        role_sig = s_key

                        # Avoid creating duplicate variables if multiple options use same role
                        if role_sig in processed_roles:
                            continue
                        processed_roles.add(role_sig)

                        # Fetch eligible workers for this specific role + time
                        logger.debug(f"Candidate search: Shift={shift.name}, Skills={req.required_skills}")
                        
                        candidates = self._data_manager.get_eligible_workers(
                            time_window=shift.time_window,
                            required_skills=req.required_skills
                        )
                        
                        logger.debug(f"  Found {len(candidates)} eligible candidates")
                        
                        # CRITICAL DEBUG: If no candidates, manually check all workers
                        if len(candidates) == 0:
                            logger.warning(f"   NO CANDIDATES FOUND! Performing manual diagnostic...")
                            
                            all_workers = self._data_manager.get_all_workers()
                            logger.debug(f"  Zero-candidate diagnostic: {len(all_workers)} total workers")
                            
                            for worker in all_workers:
                                rejection_reasons = []
                                
                                # Check 1: Availability (Date + Time matching)
                                has_availability = False
                                if worker.availability:
                                    for avail_window in worker.availability:
                                        if (avail_window.start <= shift.time_window.start and
                                            avail_window.end >= shift.time_window.end):
                                            has_availability = True
                                            break
                                else:
                                    rejection_reasons.append("No availability windows")
                                
                                if not has_availability:
                                    rejection_reasons.append("Availability doesn't cover shift time")
                                
                                # Check 2: Skills matching
                                has_skills = True
                                missing_skills = []
                                for skill_name, required_level in req.required_skills.items():
                                    if skill_name not in worker.skills:
                                        has_skills = False
                                        missing_skills.append(skill_name)
                                    elif worker.skills.get(skill_name, 0) < required_level:
                                        has_skills = False
                                        missing_skills.append(f"{skill_name} (has {worker.skills.get(skill_name)}, needs {required_level})")
                                
                                if not has_skills:
                                    rejection_reasons.append(f"Missing skills: {missing_skills}")
                                
                                if rejection_reasons:
                                    logger.debug(f"    {worker.name}: REJECTED — {' | '.join(rejection_reasons)}")
                                else:
                                    logger.warning(f"    {worker.name}: passes manual checks but was filtered by data manager")

                        for worker in candidates:
                            # Unique Key: Worker + Shift + Task + Role
                            key = (worker.worker_id, shift.shift_id, task.task_id, role_sig)


                            if key not in x_vars:
                                x_name = f"X_{worker.worker_id}_{shift.shift_id}_{task.task_id}_{hash(role_sig)}"
                                x_var = solver.IntVar(0, 1, x_name)
                                x_vars[key] = x_var

                                # Indexing
                                worker_global_assignments[worker.worker_id].append((shift, x_var))
                                worker_shift_assignments[(worker.worker_id, shift.shift_id)].append(x_var)

        return SolverContext(
            solver=solver,
            x_vars=x_vars,
            y_vars=y_vars,
            shifts=shifts,
            workers=workers,
            worker_shift_assignments=worker_shift_assignments,
            worker_global_assignments=worker_global_assignments,
            task_metadata=task_metadata
        )

    def solve(self) -> Dict[str, Any]:
        """Standard execution flow."""
        # 1. Build Base Model
        context = self._build_optimization_context()
        logger.info("Context built — applying constraints")

        # 2. Apply All Registered Constraints
        self._constraint_registry.apply_all(context)
        logger.info("Constraints applied")

        # --- Objective Audit (DEBUG level) ---
        objective = context.solver.Objective()
        non_zero_coeffs = 0
        total_score_potential = 0.0

        for x_var in context.x_vars.values():
            coeff = objective.GetCoefficient(x_var)
            if coeff != 0:
                non_zero_coeffs += 1
                total_score_potential += abs(coeff)

        logger.debug(f"Objective: {non_zero_coeffs} vars with coefficients, total potential {total_score_potential}")

        # 3. Solve
        context.solver.Objective().SetMaximization()
        status = context.solver.Solve()

        # 4. Format Output
        result_data = {
            "status": "Unknown",
            "assignments": [],
            "objective_value": 0,
            "violations": {},
            "penalty_breakdown": {},
            "theoretical_max_score": total_score_potential
        }

        if status in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
            result_data["status"] = "Optimal" if status == pywraplp.Solver.OPTIMAL else "Feasible"
            result_data["objective_value"] = context.solver.Objective().Value()
            result_data["violations"] = self._constraint_registry.get_violations(context)
            result_data["penalty_breakdown"] = self._constraint_registry.get_penalty_breakdown(context)
            self._extract_assignments(context, result_data)
        else:
            result_data["status"] = "Infeasible"
            # Optional: Auto-trigger diagnosis here or let the caller decide

        return result_data

    def diagnose_infeasibility(self) -> str:
        """
        Diagnoses why a schedule is impossible by applying constraints incrementally.
        Returns a human-readable error message identifying the culprit.

        Now includes PRE-FLIGHT CHECKS for common issues:
        1. Skill gaps (shifts require skills no worker has)
        2. Availability gaps (shifts on days when no one is available)
        """
        # PRE-FLIGHT CHECK 1: Skill Gaps
        skill_gap = self._check_skill_gaps()
        if skill_gap:
            return skill_gap

        # PRE-FLIGHT CHECK 2: Availability Gaps
        avail_gap = self._check_availability_gaps()
        if avail_gap:
            return avail_gap

        # 1. Test Base Model (Physics only)
        # We assume structural constraints (like "choose 1 option") are always true.
        context = self._build_optimization_context()
        if context.solver.Solve() not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
             return "CRITICAL: The problem is structurally impossible even without constraints. Check if you have ANY workers eligible for the tasks."

        # 2. Test Hard Constraints One by One
        hard_constraints = self._constraint_registry.get_hard_constraints()

        # We rebuild the context for every check to isolate the constraint completely
        for constraint in hard_constraints:
            temp_context = self._build_optimization_context()
            constraint.apply(temp_context)

            status = temp_context.solver.Solve()
            if status not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
                return f"FAILURE: The constraint '{constraint.name}' caused the infeasibility. This usually means: {self._get_friendly_error(constraint.name)}"

        # 3. Test Combination (Greedy Approach)
        # If all pass individually, start stacking them
        context = self._build_optimization_context()
        active_constraints = []

        for constraint in hard_constraints:
            constraint.apply(context)
            active_constraints.append(constraint.name)

            if context.solver.Solve() not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
                 return f"CONFLICT: The system worked until we added '{constraint.name}'. It conflicts with one of these previous rules: {active_constraints[:-1]}."

        return "Unknown Error: Solvable with hard constraints. Issue might be numerical or objective related."

    def _check_skill_gaps(self) -> Optional[str]:
        """
        Check if shifts require skills that no worker possesses.

        Returns:
            Error message if a skill gap is found, None otherwise.
        """
        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()

        # Build set of all worker skills
        all_worker_skills = set()
        for worker in workers:
            if worker.skills:
                all_worker_skills.update(worker.skills.keys())

        # Check each shift's requirements
        missing_skills = []
        for shift in shifts:
            for task in shift.tasks:
                for option in task.options:
                    for req in option.requirements:
                        for skill_name in req.required_skills.keys():
                            if skill_name not in all_worker_skills:
                                missing_skills.append({
                                    'shift': shift.name,
                                    'task': task.name,
                                    'skill': skill_name
                                })

        if missing_skills:
            # Format a user-friendly message
            skill_list = list(set(m['skill'] for m in missing_skills))
            shift_list = list(set(m['shift'] for m in missing_skills))

            return (
                f"SKILL GAP: The following skills are required but no worker possesses them:\n"
                f"  Missing skills: {', '.join(skill_list)}\n"
                f"  Affected shifts: {', '.join(shift_list)}\n\n"
                f"Solution: Either add workers with these skills, or remove the skill requirements from the affected shifts."
            )

        return None

    def _check_availability_gaps(self) -> Optional[str]:
        """
        Check if any shift is on a day/time when no workers are available.

        Returns:
            Error message if an availability gap is found, None otherwise.
        """
        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()

        uncovered_shifts = []

        for shift in shifts:
            shift_start = shift.time_window.start
            shift_end = shift.time_window.end

            # Check if ANY worker is available for this shift
            has_available_worker = False

            for worker in workers:
                if not worker.availability:
                    continue

                for avail_window in worker.availability:
                    # Check if availability covers the shift
                    if (avail_window.start <= shift_start and
                        avail_window.end >= shift_end):
                        has_available_worker = True
                        break

                if has_available_worker:
                    break

            if not has_available_worker:
                # Extract day name from shift date
                day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
                day_idx = shift_start.weekday()
                day_name = day_names[day_idx] if 0 <= day_idx < 7 else str(shift_start.date())

                uncovered_shifts.append({
                    'shift': shift.name,
                    'day': day_name,
                    'time': f"{shift_start.strftime('%H:%M')}-{shift_end.strftime('%H:%M')}"
                })

        if uncovered_shifts:
            # Format a user-friendly message
            shift_details = [f"  - {s['shift']} ({s['day']} {s['time']})" for s in uncovered_shifts]

            return (
                f"AVAILABILITY GAP: No workers are available for the following shifts:\n"
                + "\n".join(shift_details) + "\n\n"
                f"Solution: Either add workers who are available during these times, "
                f"update existing workers' availability, or remove these shifts."
            )

        return None

    def _get_friendly_error(self, name: str) -> str:
        """Helper to translate technical names to user hints."""
        if "coverage" in name:
            return "Not enough eligible workers to fill the required slots for a task."
        if "overlap" in name:
            return "A worker is assigned to overlapping shifts (Time paradox)."
        if "exclusivity" in name:
            return "A worker is trying to do two roles in the same shift."
        if "ban" in name:
            return "Two workers who are banned from working together are the only ones available."
        return "Constraint logic violation."

    def _extract_assignments(self, context: SolverContext, result_data: Dict[str, Any]) -> None:
        """Extracts decision variables into a human-readable assignment list.

        Iterates through the solved decision variables (X), retrieves the corresponding
        domain objects (Worker, Shift, Task), and calculates the specific score
        contribution for each assignment (e.g., preference bonuses).

        Args:
            context (SolverContext): The solved optimization context containing
                variables and domain objects.
            result_data (Dict[str, Any]): The results dictionary to populate.
                Modifies the 'assignments' list in-place.
        """
        # Look up configured preference values from the constraint registry
        pref_constraint = next(
            (c for c in self._constraint_registry._constraints
             if isinstance(c, WorkerPreferencesConstraint) and c.enabled),
            None
        )

        for key, x_var in context.x_vars.items():
            # Filter for assigned variables (binary value approx 1.0)
            if x_var.solution_value() > 0.5:
                w_id, s_id, t_id, role_sig = key

                # Retrieve domain objects
                worker = self._data_manager.get_worker(w_id)
                shift = self._data_manager.get_shift(s_id)

                # Resolve Task Name
                task_name = "Unknown"
                if shift:
                    for t in shift.tasks:
                        if t.task_id == t_id:
                            task_name = t.name
                            break

                if worker and shift:
                    # --- Score Breakdown Calculation ---
                    current_score = 0
                    breakdown_reasons: List[str] = []

                    # 1. Worker Preferences
                    # Keep this aligned with WorkerPreferencesConstraint.apply()
                    # so assignment-level explainability matches objective scoring.
                    if pref_constraint:
                        raw_pref_score = worker.calculate_preference_score(shift.time_window)

                        if raw_pref_score > 0:
                            current_score += pref_constraint.preference_reward
                            breakdown_reasons.append(f"+{pref_constraint.preference_reward} (Pref)")
                        elif raw_pref_score < 0:
                            current_score += pref_constraint.preference_penalty
                            breakdown_reasons.append(f"{pref_constraint.preference_penalty} (Avoid)")

                    # (Future: Add logic here for wage costs, skill matching bonuses, etc.)

                    # Format breakdown string
                    breakdown_str = ", ".join(breakdown_reasons) if breakdown_reasons else "-"
                    # -----------------------------------

                    # Format Role Details
                    skills_list = list(role_sig)
                    role_str = f"Skills: {skills_list}"

                    result_data["assignments"].append({
                        "worker_name": worker.name,
                        "shift_name": shift.name,
                        "time": str(shift.time_window),
                        "task": task_name,
                        "role_details": role_str,
                        "score": current_score,
                        "score_breakdown": breakdown_str
                    })


