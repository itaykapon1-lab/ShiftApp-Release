"""
Constraint Registry Module.

This module implements the central registry for managing scheduling constraints.
It acts as the orchestrator that holds all available constraints, toggles their
status (enabled/disabled), applies them to the solver in the correct order,
and aggregates violation reports.
"""

import logging
from typing import List, Dict, Optional, Any

from solver.constraints.base import (
    IConstraint,
    ConstraintType,
    SolverContext,
    ConstraintViolation
)
from solver.constraints.static_hard import CoverageConstraint, OverlapPreventionConstraint, \
    IntraShiftExclusivityConstraint

logger = logging.getLogger(__name__)


class ConstraintRegistry:
    """Central registry for managing and applying scheduling constraints.

    The registry maintains a collection of IConstraint objects. It allows for
    dynamic configuration (enabling/disabling rules) and ensures that constraints
    are applied to the solver in a deterministic order (Hard constraints first,
    then Soft constraints).
    """

    def __init__(self):
        """Initializes an empty constraint registry."""
        self._constraints: List[IConstraint] = []

    def register(self, constraint: IConstraint) -> None:
        """Adds a new constraint to the registry.

        Args:
            constraint: The constraint instance to register.

        Raises:
            ValueError: If a constraint with the same name already exists.
        """
        if any(c.name == constraint.name for c in self._constraints):
            raise ValueError(f"Constraint '{constraint.name}' already registered")

        self._constraints.append(constraint)
        logger.info(
            "Registered constraint: %s (Type: %s, Kind: %s)",
            constraint.name,
            constraint.type.value,
            constraint.kind.value
        )


    def apply_all(self, context: SolverContext) -> None:
        """Applies all enabled constraints to the solver context.

        The application order is strictly enforcing:
        1. HARD constraints (Feasibility)
        2. SOFT constraints (Optimization)

        Args:
            context: The initialized solver context containing variables and data.
        """
        hard_count = 0
        soft_count = 0

        # Phase 1: Apply Hard Constraints (feasibility rules).
        # Hard constraints call solver.Add() to create equations that the
        # solver MUST satisfy. The solution is infeasible if any is violated.
        # Applied first so soft constraints operate within feasible bounds.
        for constraint in self._constraints:
            if constraint.enabled and constraint.type == ConstraintType.HARD:
                logger.debug("Applying hard constraint: %s", constraint.name)
                constraint.apply(context)
                hard_count += 1

        # Phase 2: Apply Soft Constraints (optimization preferences).
        # Soft constraints add penalty/reward coefficients to the objective
        # function. The solver will try to minimize penalties (maximize the
        # objective) but is allowed to violate these if needed for feasibility.
        for constraint in self._constraints:
            if constraint.enabled and constraint.type == ConstraintType.SOFT:
                logger.debug("Applying soft constraint: %s", constraint.name)
                constraint.apply(context)
                soft_count += 1

        logger.info("Applied %d hard and %d soft constraints.", hard_count, soft_count)

    def add_core_constraints(self) -> None:
        """Registers the fundamental laws of scheduling (Physics).

        Call this method to ensure the schedule is valid (shifts are staffed,
        no overlaps, no double roles).
        """
        existing_names = {c.name for c in self._constraints}

        core_rules = [
            CoverageConstraint(),
            IntraShiftExclusivityConstraint(),
            OverlapPreventionConstraint()
        ]

        for rule in core_rules:
            if rule.name not in existing_names:
                self.register(rule)
                logger.info(f"Auto-added core constraint: {rule.name}")

    def get_violations(self, context: SolverContext) -> Dict[str, List[ConstraintViolation]]:
        """Collects all violations from soft constraints after solving.

        This method should be called only after the solver has successfully found
        a solution (Optimal or Feasible).

        Args:
            context: The solved context with solution values.

        Returns:
            Dict[str, List[ConstraintViolation]]: A map where keys are constraint
            names and values are lists of specific violation details.
        """
        violations: Dict[str, List[ConstraintViolation]] = {}

        for constraint in self._constraints:
            # Only soft constraints produce "violations" that we track.
            # Hard constraints are binary (satisfied/unsatisfied) handled by the solver status.
            if constraint.type == ConstraintType.SOFT and constraint.enabled:
                constraint_violations = constraint.get_violations(context)
                if constraint_violations:
                    violations[constraint.name] = constraint_violations

        return violations

    def get_penalty_breakdown(self, context: SolverContext) -> Dict[str, Dict[str, Any]]:
        """Computes a penalty breakdown by constraint type.

        Aggregates violations into a summary showing total penalty
        per constraint type for score explainability.

        Args:
            context: The solved context with solution values.

        Returns:
            Dict with constraint names as keys and dicts containing:
                - total_penalty: Sum of all penalties for this constraint
                - violation_count: Number of violations
                - violations: List of violation descriptions
        """
        violations = self.get_violations(context)
        breakdown: Dict[str, Dict[str, Any]] = {}

        for constraint_name, violation_list in violations.items():
            total_penalty = sum(v.penalty for v in violation_list)
            breakdown[constraint_name] = {
                "total_penalty": total_penalty,
                "violation_count": len(violation_list),
                "violations": [
                    {
                        "description": v.description,
                        "penalty": v.penalty,
                        "observed_value": v.observed_value,
                        "limit_value": v.limit_value,
                        "metadata": v.metadata,
                    }
                    for v in violation_list
                ]
            }

        return breakdown

    def get_hard_constraints(self) -> List[IConstraint]:
        """Retrieves all registered constraints marked as HARD type.

        This is primarily used by the solver's diagnostic tool to test
        feasibility incrementally.

        Returns:
            List[IConstraint]: A list of enabled constraints where type is HARD.
        """
        return [
            c for c in self._constraints
            if c.type == ConstraintType.HARD and c.enabled
        ]

    def enable(self, constraint_name: str) -> None:
        """Enables a specific constraint by name.

        Args:
            constraint_name: The unique identifier of the constraint.
        """
        constraint = self._find(constraint_name)
        if constraint:
            constraint.enabled = True
            logger.info("Constraint '%s' enabled.", constraint_name)
        else:
            logger.warning("Attempted to enable unknown constraint: %s", constraint_name)

    def disable(self, constraint_name: str) -> None:
        """Disables a specific constraint by name.

        Args:
            constraint_name: The unique identifier of the constraint.
        """
        constraint = self._find(constraint_name)
        if constraint:
            constraint.enabled = False
            logger.info("Constraint '%s' disabled.", constraint_name)
        else:
            logger.warning("Attempted to disable unknown constraint: %s", constraint_name)

    def _find(self, name: str) -> Optional[IConstraint]:
        """Helper to find a constraint object by name.

        Args:
            name: The constraint name to search for.

        Returns:
            The IConstraint object if found, otherwise None.
        """
        return next((c for c in self._constraints if c.name == name), None)
