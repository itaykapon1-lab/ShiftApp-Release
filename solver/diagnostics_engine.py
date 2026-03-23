"""Diagnostic helpers for solver infeasibility and preflight analysis.

This module provides two categories of diagnostic tools:

1. **Preflight Checks** (cheap, O(shifts * workers) data scans):
   Run BEFORE building the MILP model to catch obviously doomed problems.
   Ordered from cheapest to most expensive: skill gaps -> availability -> headcount.

2. **Staged Infeasibility Diagnosis** (expensive, requires solving):
   Run AFTER a solve attempt fails. Incrementally tests constraints to isolate
   the specific rule or combination of rules causing infeasibility.
   Stages: base model -> individual constraints -> pairwise conflicts.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.task_model import Requirement
from domain.worker_model import Worker
from repositories.interfaces import IDataManager
from solver.constraints.base import SolverContext

logger = logging.getLogger(__name__)

# Callback signatures for dependency injection — the DiagnosticsEngine does NOT
# directly depend on ShiftSolver or ConstraintRegistry to avoid circular imports.
# Instead, it receives factory functions that create fresh solver contexts and
# retrieve constraint lists on demand.
BuildContextFn = Callable[[], SolverContext]
HardConstraintsFn = Callable[[], List[Any]]
CandidateProviderFn = Callable[[Shift, Requirement], List[Worker]]


class DiagnosticsEngine:
    """Runs preflight checks and staged infeasibility diagnosis."""

    def __init__(
        self,
        data_manager: IDataManager,
        build_context: BuildContextFn,
        get_hard_constraints: HardConstraintsFn,
        candidate_provider: CandidateProviderFn,
    ) -> None:
        self._data_manager = data_manager
        self._build_context = build_context
        self._get_hard_constraints = get_hard_constraints
        self._candidate_provider = candidate_provider

    def diagnose_infeasibility(self) -> str:
        """Diagnoses why a schedule is impossible using a 4-stage escalation strategy.

        Stage 1 — Preflight checks (cheap data-only analysis, no solver):
          Catches skill gaps, availability gaps, and headcount gaps via pure
          data inspection.  Also run proactively in solver_engine.py before
          solving, but repeated here so that direct callers (e.g., tests)
          get the same result.

        Stage 2 — Base model test (one solve, no hard constraints):
          Checks if the problem is structurally impossible even without any
          constraint rules (e.g., zero eligible workers for any task).

        Stage 3 — Individual constraint isolation (N solves):
          Tests each hard constraint alone against a fresh model. If one
          constraint makes the problem infeasible on its own, it's the culprit.

        Stage 4 — Constraint stacking / conflict detection (N solves):
          Applies constraints one-by-one on a shared model. When adding
          constraint K makes the model infeasible, K conflicts with {1..K-1}.
        """
        # Stage 1: Cheap preflight checks (idempotent — safe to repeat).
        preflight_failure = self.run_preflight_checks()
        if preflight_failure:
            return preflight_failure

        # Stage 2: Can the base model (variables + sum(Y)==1, no hard constraints)
        # be solved at all? If not, the problem structure itself is broken.
        base_model_failure = self.diagnose_base_model_failure()
        if base_model_failure:
            return base_model_failure

        hard_constraints = self._get_hard_constraints()

        # Stage 3: Test each hard constraint in isolation.
        individual_failure = self.diagnose_individual_hard_constraints(hard_constraints)
        if individual_failure:
            return individual_failure

        # Stage 4: Stack constraints greedily to find conflicting combinations.
        conflict_failure = self.diagnose_hard_constraint_conflicts(hard_constraints)
        if conflict_failure:
            return conflict_failure

        # If all 4 stages pass, the issue is likely numerical (floating-point)
        # or related to the objective function, not the constraint set.
        return (
            "Unknown Error: Solvable with hard constraints. "
            "Issue might be numerical or objective related."
        )

    def run_preflight_checks(self) -> Optional[str]:
        """Runs fast diagnostic checks before building solver models.

        Checks are ordered from cheapest to most expensive:
        1. Skill gaps — O(tasks * options * skills): pure set membership.
        2. Availability gaps — O(shifts * workers * availability_windows): datetime comparison.
        3. Headcount gaps — O(tasks * options * requirements): calls candidate_provider
           which queries the data manager's eligibility index.

        Returns the first failure message found, or None if all checks pass.
        """
        # Check 1: Are there tasks where no staffing option uses only available skills?
        skill_gap = self.check_skill_gaps()
        if skill_gap:
            return skill_gap

        # Check 2: Are there shifts where no worker is available at all?
        avail_gap = self.check_availability_gaps()
        if avail_gap:
            return avail_gap

        # Check 3: Are there tasks where no option has enough eligible workers?
        headcount_gap = self.check_headcount_gaps()
        if headcount_gap:
            return headcount_gap

        return None

    def diagnose_base_model_failure(self) -> Optional[str]:
        """Checks whether the base model is infeasible before any hard constraints.

        The "base model" consists of:
        - Y variables with sum(Y) == 1 per task (structural constraint).
        - X variables for eligible workers.
        - NO hard constraints (coverage, exclusivity, overlap are NOT applied).

        If this model is already infeasible, the problem is structurally broken —
        typically because some task has zero eligible workers for ALL its options,
        making the sum(Y) == 1 constraint unsatisfiable.
        """
        context = self._build_context()
        if context.solver.Solve() not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
            return (
                "CRITICAL: The problem is structurally impossible even without constraints. "
                "Check if you have ANY workers eligible for the tasks."
            )
        return None

    def diagnose_individual_hard_constraints(
        self,
        hard_constraints: List[Any],
    ) -> Optional[str]:
        """Tests each hard constraint in isolation against a fresh base model.

        For each constraint, a brand-new solver context is built (clean slate)
        and only that single constraint is applied. If the model becomes infeasible,
        that constraint alone is sufficient to make the problem unsolvable —
        a clear root cause identification.

        This is more expensive than preflight checks (N separate solves) but
        provides precise blame attribution.
        """
        for constraint in hard_constraints:
            # Build a fresh context with NO constraints applied (clean baseline).
            temp_context = self._build_context()

            # Apply ONLY this one constraint to the clean model.
            constraint.apply(temp_context)

            status = temp_context.solver.Solve()
            if status not in [pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE]:
                return (
                    f"FAILURE: The constraint '{constraint.name}' caused the infeasibility. "
                    f"This usually means: {self.get_friendly_error(constraint.name)}"
                )

        return None

    def diagnose_hard_constraint_conflicts(
        self,
        hard_constraints: List[Any],
    ) -> Optional[str]:
        """Stacks hard constraints greedily on a shared model to locate conflicts.

        Unlike diagnose_individual_hard_constraints (which tests each in isolation),
        this method adds constraints ONE AT A TIME to a SINGLE model, solving after
        each addition. When constraint K causes infeasibility, it tells us that K
        conflicts with the combination of constraints {1, 2, ..., K-1}.

        This identifies interaction effects that only emerge when multiple rules
        are combined (e.g., coverage + overlap can conflict when workers are scarce).
        """
        context = self._build_context()
        active_constraints = []

        for constraint in hard_constraints:
            # Add this constraint to the accumulating model (not a fresh one).
            constraint.apply(context)
            active_constraints.append(constraint.name)

            # Solve the model with all constraints applied so far.
            if context.solver.Solve() not in [
                pywraplp.Solver.OPTIMAL,
                pywraplp.Solver.FEASIBLE,
            ]:
                # The model was feasible with constraints {1..K-1} but became
                # infeasible after adding constraint K. This means K interacts
                # with one or more of the previously active constraints.
                return (
                    f"CONFLICT: The system worked until we added '{constraint.name}'. "
                    f"It conflicts with one of these previous rules: {active_constraints[:-1]}."
                )

        return None

    def run_zero_candidate_diagnostic(
        self,
        shift: Shift,
        req: Requirement,
    ) -> None:
        """Logs a detailed manual rejection analysis when zero workers are eligible.

        This is a DEBUG-level diagnostic triggered during variable construction
        when no candidates are found for a (shift, requirement) pair. It manually
        re-evaluates every worker against the eligibility criteria to explain
        exactly WHY each was rejected. This is invaluable for debugging data
        issues where workers are unexpectedly ineligible.

        If a worker passes all manual checks but was still filtered by the data
        manager, it's logged as a WARNING — this indicates a discrepancy between
        the manual check logic here and the data manager's eligibility query.
        """
        all_workers = self._data_manager.get_all_workers()
        logger.debug("  Zero-candidate diagnostic: %d total workers", len(all_workers))

        for worker in all_workers:
            rejection_reasons = []

            # --- Check 1: Availability window containment ---
            # The worker must have at least one availability window that fully
            # covers the shift (avail.start <= shift.start AND avail.end >= shift.end).
            has_availability = False
            if worker.availability:
                for avail_window in worker.availability:
                    if (
                        avail_window.start <= shift.time_window.start
                        and avail_window.end >= shift.time_window.end
                    ):
                        has_availability = True
                        break
            else:
                rejection_reasons.append("No availability windows")

            if not has_availability:
                rejection_reasons.append("Availability doesn't cover shift time")

            # --- Check 2: Skill requirements ---
            # The worker must possess every required skill at the required level.
            # Defensive: normalize skill names to Title Case for case-insensitive
            # matching, consistent with Worker.set_skill_level() convention.
            has_skills = True
            missing_skills = []
            for skill_name, required_level in req.required_skills.items():
                normalized_skill = skill_name.strip().title()
                if normalized_skill not in worker.skills:
                    # Worker lacks the skill entirely.
                    has_skills = False
                    missing_skills.append(skill_name)
                elif worker.skills.get(normalized_skill, 0) < required_level:
                    # Worker has the skill but at an insufficient level.
                    has_skills = False
                    missing_skills.append(
                        f"{skill_name} (has {worker.skills.get(normalized_skill)}, needs {required_level})"
                    )

            if not has_skills:
                rejection_reasons.append(f"Missing skills: {missing_skills}")

            if rejection_reasons:
                logger.debug(
                    "    %s: REJECTED - %s",
                    worker.name,
                    " | ".join(rejection_reasons),
                )
            else:
                # Worker passes all manual checks — this means the data manager's
                # eligibility query is more restrictive than our manual check.
                # This warrants investigation.
                logger.warning(
                    "    %s: passes manual checks but was filtered by data manager",
                    worker.name,
                )

    def check_skill_gaps(self) -> Optional[str]:
        """Check if all staffing options for a task require skills no worker has.

        A task is only flagged if EVERY one of its options requires at least one
        skill that no worker possesses.  If any single option uses only skills
        present in the worker pool, the task passes (the solver can pick that
        option via the ``sum(Y_options) == 1`` constraint).
        """
        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()

        # Build the universe of all skills present in the worker pool.
        # This is a simple set-membership check — we don't care about levels here,
        # only whether the skill EXISTS in the pool at all.
        # Defensive: normalize to Title Case to match Worker.set_skill_level() convention.
        all_worker_skills: set[str] = set()
        for worker in workers:
            if worker.skills:
                all_worker_skills.update(
                    s.strip().title() for s in worker.skills.keys()
                )

        gaps: list[dict[str, str]] = []
        for shift in shifts:
            for task in shift.tasks:
                # Feasibility gate: at least one option must use only skills
                # that exist in the worker pool. This mirrors the solver's
                # sum(Y_options) == 1 constraint — only one option needs to work.
                task_has_feasible_option = False

                for option in task.options:
                    # Collect skills required by this option that NO worker has.
                    option_missing = []
                    for req in option.requirements:
                        for skill_name in req.required_skills.keys():
                            if skill_name.strip().title() not in all_worker_skills:
                                option_missing.append(skill_name)

                    if not option_missing:
                        # This option uses only available skills — task is feasible.
                        task_has_feasible_option = True
                        break  # No need to check remaining options.

                if not task_has_feasible_option:
                    # ALL options require at least one missing skill — task is doomed.
                    gaps.append({
                        "shift": shift.name,
                        "task": task.name,
                    })

        if not gaps:
            return None

        task_details = [f"  - Shift '{g['shift']}', Task '{g['task']}'" for g in gaps]
        return (
            "SKILL GAP: Every staffing option for the following tasks requires "
            "skills that no worker possesses:\n"
            + "\n".join(task_details)
            + "\n\nSolution: Add workers with the missing skills, or add a "
            "staffing option that uses only available skills."
        )

    def check_availability_gaps(self) -> Optional[str]:
        """Check if any shift is on a day/time when no workers are available.

        Uses a containment check: a worker covers a shift if at least one of
        their availability windows fully contains the shift's time window
        (avail.start <= shift.start AND avail.end >= shift.end).

        This is a necessary-but-not-sufficient check — a shift may have available
        workers who lack the required skills, which is caught by check_headcount_gaps().
        """
        shifts = self._data_manager.get_all_shifts()
        workers = self._data_manager.get_all_workers()

        uncovered_shifts = []

        for shift in shifts:
            shift_start = shift.time_window.start
            shift_end = shift.time_window.end

            has_available_worker = False

            for worker in workers:
                if not worker.availability:
                    continue  # Workers without availability windows can't cover any shift.

                # Check if any of this worker's availability windows fully contain
                # the shift's time range. Partial overlap is NOT sufficient.
                for avail_window in worker.availability:
                    if avail_window.start <= shift_start and avail_window.end >= shift_end:
                        has_available_worker = True
                        break

                if has_available_worker:
                    break  # At least one worker can cover this shift — move on.

            if not has_available_worker:
                day_names = [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
                day_idx = shift_start.weekday()
                day_name = day_names[day_idx] if 0 <= day_idx < 7 else str(shift_start.date())

                uncovered_shifts.append(
                    {
                        "shift": shift.name,
                        "day": day_name,
                        "time": f"{shift_start.strftime('%H:%M')}-{shift_end.strftime('%H:%M')}",
                    }
                )

        if uncovered_shifts:
            shift_details = [f"  - {s['shift']} ({s['day']} {s['time']})" for s in uncovered_shifts]

            return (
                "AVAILABILITY GAP: No workers are available for the following shifts:\n"
                + "\n".join(shift_details)
                + "\n\n"
                + "Solution: Either add workers who are available during these times, "
                + "update existing workers' availability, or remove these shifts."
            )

        return None

    def check_headcount_gaps(self) -> Optional[str]:
        """Checks whether at least one option per task is headcount-feasible.

        This is the most precise preflight check. For each task, it evaluates
        every staffing option and checks whether the number of eligible workers
        (available + skilled) meets or exceeds the required headcount for each
        role in that option. A task is flagged only if ALL its options fail.

        Uses the candidate_provider callback to query eligibility, which applies
        the same logic as the variable builder (availability + skill matching).
        """
        gaps = []

        for shift in self._data_manager.get_all_shifts():
            for task in shift.tasks:
                option_failures = []
                # Feasibility gate: mirrors the solver's sum(Y) == 1 constraint.
                # Only one option needs to be feasible for the task to be solvable.
                task_has_feasible_option = False

                for opt_idx, option in enumerate(task.options):
                    requirement_failures = []

                    for req in option.requirements:
                        # Query eligible workers using the same provider the
                        # variable builder uses — ensures consistency.
                        eligible_workers = self._candidate_provider(shift, req)
                        eligible_count = len(eligible_workers)
                        # Check: does the eligible pool meet the headcount demand?
                        # e.g., if we need 3 Cooks but only 2 are eligible, fail.
                        if eligible_count < req.count:
                            requirement_failures.append(
                                {
                                    "skills": sorted(req.required_skills.keys()),
                                    "required": req.count,
                                    "eligible": eligible_count,
                                }
                            )

                    if not requirement_failures:
                        # All roles in this option have sufficient candidates.
                        task_has_feasible_option = True
                        break  # No need to check remaining options.

                    option_failures.append(
                        {
                            "option_index": opt_idx,
                            "requirement_failures": requirement_failures,
                        }
                    )

                if not task_has_feasible_option:
                    gaps.append(
                        {
                            "shift": shift.name,
                            "task": task.name,
                            "option_failures": option_failures,
                        }
                    )

        if not gaps:
            return None

        lines = ["HEADCOUNT GAP: No staffing option has enough eligible workers for these tasks:"]
        for gap in gaps:
            lines.append(f"  - Shift '{gap['shift']}', Task '{gap['task']}'")
            for option_failure in gap["option_failures"]:
                failures = ", ".join(
                    (
                        f"option {option_failure['option_index']} role {failure['skills']} "
                        f"needs {failure['required']} but only {failure['eligible']} eligible"
                    )
                    for failure in option_failure["requirement_failures"]
                )
                lines.append(f"    {failures}")

        lines.append("")
        lines.append(
            "Solution: Add more eligible workers, lower the required headcount, "
            "or add a feasible staffing option."
        )
        return "\n".join(lines)

    def get_friendly_error(self, name: str) -> str:
        """Translates technical constraint names to plain-English hints."""
        if "coverage" in name:
            return "Not enough eligible workers to fill the required slots for a task."
        if "overlap" in name:
            return "A worker is assigned to overlapping shifts (Time paradox)."
        if "exclusivity" in name:
            return "A worker is trying to do two roles in the same shift."
        if "ban" in name:
            return "Two workers who are banned from working together are the only ones available."
        return "Constraint logic violation."
