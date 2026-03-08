"""Dynamic Constraints Implementation.

This module contains constraint classes that are instantiated based on
dynamic user rules (e.g., from CSV configuration).
"""

import logging
from typing import Dict, List, Tuple

from ortools.linear_solver import pywraplp

from app.core.constants import MUTUAL_EXCLUSION_PENALTY, CO_LOCATION_PENALTY
from solver.constraints.base import (
    BaseConstraint,
    ConstraintKind,
    ConstraintType,
    ConstraintViolation,
    SolverContext,
)

logger = logging.getLogger(__name__)


class MutualExclusionConstraint(BaseConstraint):
    """Enforces that two specific workers cannot work in the same shift.

    If set to HARD, the solver will forbid any overlap.
    If set to SOFT, the solver will penalize overlaps.
    """

    def __init__(
        self,
        worker_a_id: str,
        worker_b_id: str,
        strictness: ConstraintType = ConstraintType.HARD,
        penalty: float = MUTUAL_EXCLUSION_PENALTY,
    ):
        super().__init__(
            name=f"ban_{worker_a_id}_{worker_b_id}",
            constraint_type=strictness,
            kind=ConstraintKind.DYNAMIC,
        )
        self.w_a = worker_a_id
        self.w_b = worker_b_id
        self.penalty = penalty
        # (worker_a_id, worker_b_id, shift_id, shift_name, violation_var)
        self._soft_violation_markers: List[Tuple[str, str, str, str, pywraplp.Variable]] = []

    @staticmethod
    def _normalize_worker_id(worker_id: str) -> str:
        """Normalize IDs for tolerant matching (trim + string cast)."""
        return str(worker_id).strip()

    @staticmethod
    def _resolve_worker_id(context: SolverContext, raw_worker_id: str) -> str | None:
        """Resolve a worker ID against context workers using strict+case-insensitive lookup."""
        candidate = MutualExclusionConstraint._normalize_worker_id(raw_worker_id)
        if not candidate:
            logger.warning("Dynamic constraint contains an empty worker_id")
            return None

        if any(w.worker_id == candidate for w in context.workers):
            return candidate

        by_lower = {w.worker_id.lower(): w.worker_id for w in context.workers}
        resolved = by_lower.get(candidate.lower())
        if resolved:
            logger.warning(
                "Normalized worker ID '%s' to '%s' in dynamic constraint",
                raw_worker_id,
                resolved,
            )
            return resolved

        logger.warning(
            "Worker ID '%s' from dynamic constraint was not found in solver context; skipping rule",
            raw_worker_id,
        )
        return None

    @staticmethod
    def _worker_name_map(context: SolverContext) -> Dict[str, str]:
        return {worker.worker_id: worker.name for worker in context.workers}

    def apply(self, context: SolverContext) -> None:
        """Applies the mutual exclusion logic using summed assignment variables."""
        solver = context.solver
        self._soft_violation_markers.clear()

        worker_a_id = self._resolve_worker_id(context, self.w_a)
        worker_b_id = self._resolve_worker_id(context, self.w_b)
        if not worker_a_id or not worker_b_id:
            return

        for shift in context.shifts:
            vars_a = context.worker_shift_assignments.get((worker_a_id, shift.shift_id), [])
            vars_b = context.worker_shift_assignments.get((worker_b_id, shift.shift_id), [])
            if not vars_a or not vars_b:
                continue

            is_working_a = sum(vars_a)
            is_working_b = sum(vars_b)

            if self.type == ConstraintType.HARD:
                solver.Add(is_working_a + is_working_b <= 1)
            else:
                violation_var = solver.BoolVar(
                    f"violation_ban_{worker_a_id}_{worker_b_id}_{shift.shift_id}"
                )
                solver.Add(is_working_a + is_working_b - 1 <= violation_var)
                solver.Objective().SetCoefficient(violation_var, self.penalty)
                self._soft_violation_markers.append(
                    (worker_a_id, worker_b_id, shift.shift_id, shift.name, violation_var)
                )

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        if self.type != ConstraintType.SOFT:
            return []

        violations: List[ConstraintViolation] = []
        worker_names = self._worker_name_map(context)

        for worker_a_id, worker_b_id, shift_id, shift_name, violation_var in self._soft_violation_markers:
            if violation_var.solution_value() <= 0.5:
                continue

            worker_a_name = worker_names.get(worker_a_id, worker_a_id)
            worker_b_name = worker_names.get(worker_b_id, worker_b_id)
            description = (
                f"Worker {worker_a_name} and Worker {worker_b_name} were assigned together "
                f"in shift {shift_name}."
            )

            violations.append(
                ConstraintViolation(
                    constraint_name=self.name,
                    description=description,
                    penalty=self.penalty,
                    observed_value=1,
                    limit_value=0,
                    metadata={
                        "rule_type": "mutual_exclusion",
                        "worker_ids": [worker_a_id, worker_b_id],
                        "worker_names": [worker_a_name, worker_b_name],
                        "shift_id": shift_id,
                        "shift_name": shift_name,
                    },
                )
            )

        return violations


class CoLocationConstraint(BaseConstraint):
    """Enforces that if Worker A works, Worker B MUST also work (and vice versa)."""

    def __init__(
        self,
        worker_a_id: str,
        worker_b_id: str,
        strictness: ConstraintType = ConstraintType.SOFT,
        penalty: float = CO_LOCATION_PENALTY,
    ):
        super().__init__(
            name=f"pair_{worker_a_id}_{worker_b_id}",
            constraint_type=strictness,
            kind=ConstraintKind.DYNAMIC,
        )
        self.w_a = worker_a_id
        self.w_b = worker_b_id
        self.penalty = penalty
        # (worker_a_id, worker_b_id, shift_id, shift_name, diff_var, vars_a, vars_b)
        self._diff_markers: List[
            Tuple[
                str,
                str,
                str,
                str,
                pywraplp.Variable,
                List[pywraplp.Variable],
                List[pywraplp.Variable],
            ]
        ] = []
        # (active_worker_id, missing_worker_id, shift_id, shift_name, violation_var)
        self._single_side_markers: List[Tuple[str, str, str, str, pywraplp.Variable]] = []

    def apply(self, context: SolverContext) -> None:
        """Applies the co-location logic (Pairing)."""
        solver = context.solver
        self._diff_markers.clear()
        self._single_side_markers.clear()

        worker_a_id = MutualExclusionConstraint._resolve_worker_id(context, self.w_a)
        worker_b_id = MutualExclusionConstraint._resolve_worker_id(context, self.w_b)
        if not worker_a_id or not worker_b_id:
            return

        for shift in context.shifts:
            vars_a = context.worker_shift_assignments.get((worker_a_id, shift.shift_id), [])
            vars_b = context.worker_shift_assignments.get((worker_b_id, shift.shift_id), [])

            if not vars_a and not vars_b:
                continue

            if (vars_a and not vars_b) or (vars_b and not vars_a):
                valid_sum = sum(vars_a) if vars_a else sum(vars_b)

                if self.type == ConstraintType.HARD:
                    solver.Add(valid_sum == 0)
                else:
                    active_worker_id = worker_a_id if vars_a else worker_b_id
                    missing_worker_id = worker_b_id if vars_a else worker_a_id
                    violation_var = solver.BoolVar(
                        f"solo_pair_{active_worker_id}_{missing_worker_id}_{shift.shift_id}"
                    )
                    solver.Add(valid_sum <= violation_var)
                    solver.Objective().SetCoefficient(violation_var, self.penalty)
                    self._single_side_markers.append(
                        (active_worker_id, missing_worker_id, shift.shift_id, shift.name, violation_var)
                    )
                continue

            is_working_a = sum(vars_a)
            is_working_b = sum(vars_b)

            if self.type == ConstraintType.HARD:
                solver.Add(is_working_a == is_working_b)
            else:
                diff = solver.BoolVar(
                    f"diff_pair_{worker_a_id}_{worker_b_id}_{shift.shift_id}"
                )
                solver.Add(diff >= is_working_a - is_working_b)
                solver.Add(diff >= is_working_b - is_working_a)
                solver.Objective().SetCoefficient(diff, self.penalty)
                self._diff_markers.append(
                    (worker_a_id, worker_b_id, shift.shift_id, shift.name, diff, vars_a, vars_b)
                )

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        if self.type != ConstraintType.SOFT:
            return []

        violations: List[ConstraintViolation] = []
        worker_names = MutualExclusionConstraint._worker_name_map(context)

        for active_worker_id, missing_worker_id, shift_id, shift_name, violation_var in self._single_side_markers:
            if violation_var.solution_value() <= 0.5:
                continue

            active_worker_name = worker_names.get(active_worker_id, active_worker_id)
            missing_worker_name = worker_names.get(missing_worker_id, missing_worker_id)
            description = (
                f"Worker {active_worker_name} worked without required pair Worker "
                f"{missing_worker_name} in shift {shift_name}."
            )
            violations.append(
                ConstraintViolation(
                    constraint_name=self.name,
                    description=description,
                    penalty=self.penalty,
                    observed_value=1,
                    limit_value=0,
                    metadata={
                        "rule_type": "colocation",
                        "worker_ids": [active_worker_id, missing_worker_id],
                        "worker_names": [active_worker_name, missing_worker_name],
                        "primary_worker_id": active_worker_id,
                        "primary_worker_name": active_worker_name,
                        "paired_worker_id": missing_worker_id,
                        "paired_worker_name": missing_worker_name,
                        "shift_id": shift_id,
                        "shift_name": shift_name,
                    },
                )
            )

        for worker_a_id, worker_b_id, shift_id, shift_name, diff_var, vars_a, vars_b in self._diff_markers:
            if diff_var.solution_value() <= 0.5:
                continue

            working_a = sum(var.solution_value() for var in vars_a) > 0.5
            working_b = sum(var.solution_value() for var in vars_b) > 0.5

            if working_a and not working_b:
                primary_worker_id = worker_a_id
                paired_worker_id = worker_b_id
            elif working_b and not working_a:
                primary_worker_id = worker_b_id
                paired_worker_id = worker_a_id
            else:
                primary_worker_id = worker_a_id
                paired_worker_id = worker_b_id

            primary_worker_name = worker_names.get(primary_worker_id, primary_worker_id)
            paired_worker_name = worker_names.get(paired_worker_id, paired_worker_id)
            description = (
                f"Worker {primary_worker_name} worked without required pair Worker "
                f"{paired_worker_name} in shift {shift_name}."
            )
            violations.append(
                ConstraintViolation(
                    constraint_name=self.name,
                    description=description,
                    penalty=self.penalty,
                    observed_value=1,
                    limit_value=0,
                    metadata={
                        "rule_type": "colocation",
                        "worker_ids": [primary_worker_id, paired_worker_id],
                        "worker_names": [primary_worker_name, paired_worker_name],
                        "primary_worker_id": primary_worker_id,
                        "primary_worker_name": primary_worker_name,
                        "paired_worker_id": paired_worker_id,
                        "paired_worker_name": paired_worker_name,
                        "shift_id": shift_id,
                        "shift_name": shift_name,
                    },
                )
            )

        return violations

