"""Constraint Configuration Factory.

This module defines the configuration logic for scheduling constraints.
It serves as a bridge between raw data (from CSV/DB) and the actual
`Constraint` objects used by the solver.

The `ConstraintConfig` class implements the Factory Pattern to instantiate
and register constraints based on the provided settings.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
import logging

from solver.constraints.base import ConstraintType
from solver.constraints.registry import ConstraintRegistry

# Static Constraints Imports
from solver.constraints.static_soft import (
    MaxHoursPerWeekConstraint,
    AvoidConsecutiveShiftsConstraint,
    WorkerPreferencesConstraint
)

# Dynamic Constraints Imports
from solver.constraints.dynamic import (
    MutualExclusionConstraint,
    CoLocationConstraint
)

logger = logging.getLogger(__name__)


@dataclass
class ConstraintConfig:
    """Holds the configuration for all scheduling constraints.

    This class decouples the data parsing logic from the constraint
    instantiation logic. It stores primitive values (ints, strings, dicts)
    and provides a method to build a fully functional `ConstraintRegistry`.

    Attributes:
        max_hours_per_week (int): The soft limit for working hours per week.
            Defaults to 40.
        max_hours_penalty (float): The penalty score deducted from the objective
            function for every hour exceeding the limit. Defaults to -10.0.
        max_hours_strictness (ConstraintType): Defines if the rule is HARD or SOFT.
            Defaults to SOFT.
        min_rest_hours (int): The minimum required rest hours between shifts.
            Defaults to 12.
        min_rest_penalty (float): The penalty score deducted if the rest time
            is violated. Defaults to -50.0.
        min_rest_strictness (ConstraintType): Defines if the rule is HARD or SOFT.
            Defaults to SOFT.
        mutual_exclusions (List[Dict[str, Any]]): A list of rules defining
            workers who cannot work together.
            Structure: `{'worker_a': str, 'worker_b': str, 'strictness': ConstraintType}`.
        colocations (List[Dict[str, Any]]): A list of rules defining workers
            who must work together.
            Structure: `{'leader': str, 'follower': str, 'strictness': ConstraintType}`.
    """

    # Global Settings
    max_hours_per_week: int = 40
    max_hours_penalty: float = -10.0
    max_hours_strictness: ConstraintType = ConstraintType.SOFT

    min_rest_hours: int = 12
    min_rest_penalty: float = -50.0
    min_rest_strictness: ConstraintType = ConstraintType.SOFT

    # Worker preferences toggle (schema-driven)
    worker_preferences_enabled: bool = True

    # Dynamic Rules Data
    # We use default_factory to avoid shared mutable state between instances.
    mutual_exclusions: List[Dict[str, Any]] = field(default_factory=list)
    colocations: List[Dict[str, Any]] = field(default_factory=list)

    def build_registry(self) -> ConstraintRegistry:
        """Constructs a ConstraintRegistry based on the current configuration.

        This method acts as a Factory. It ensures that mandatory core constraints
        (the 'Laws of Physics' of the schedule) are always loaded, and then
        selectively instantiates optional/dynamic constraints based on the
        values stored in this config object.

        Returns:
            ConstraintRegistry: An initialized registry ready to be injected
            into the `ShiftSolver`.
        """
        registry = ConstraintRegistry()

        # 1. Inject Core Constraints (Safety Layer)
        # We explicitly add the constraints that ensure a valid schedule structure
        # (e.g., Coverage, Overlap Prevention). This prevents the solver from
        # returning empty schedules to avoid penalties.
        registry.add_core_constraints()
        if self.worker_preferences_enabled:
            registry.register(WorkerPreferencesConstraint())

        logger.debug("Core constraints injected into registry.")

        # 2. Instantiate Global Constraints
        if self.max_hours_per_week > 0:
            # Note: We currently instantiate MaxHours as a specific class.
            # If logic requires supporting HARD max hours, the class itself
            # should handle the `strictness` parameter.
            max_hours_constraint = MaxHoursPerWeekConstraint(
                max_hours=self.max_hours_per_week,
                penalty_per_hour=self.max_hours_penalty,
                strictness=self.max_hours_strictness,
            )
            registry.register(max_hours_constraint)

        if self.min_rest_hours > 0:
            rest_constraint = AvoidConsecutiveShiftsConstraint(
                min_rest_hours=self.min_rest_hours,
                penalty=self.min_rest_penalty,
                strictness=self.min_rest_strictness,
            )
            registry.register(rest_constraint)

        # 3. Instantiate Dynamic Mutual Exclusion Rules (Bans)
        for rule in self.mutual_exclusions:
            worker_a = rule.get('worker_a')
            worker_b = rule.get('worker_b')
            # Default strictness is HARD for bans unless specified otherwise
            strictness = rule.get('strictness', ConstraintType.HARD)

            if worker_a and worker_b:
                constraint = MutualExclusionConstraint(
                    worker_a_id=worker_a,
                    worker_b_id=worker_b,
                    strictness=strictness
                )
                registry.register(constraint)

        # 4. Instantiate Dynamic Co-Location Rules (Pairs)
        for rule in self.colocations:
            leader = rule.get('leader')
            follower = rule.get('follower')
            # Default strictness is SOFT for pairs unless specified otherwise
            strictness = rule.get('strictness', ConstraintType.SOFT)

            if leader and follower:
                constraint = CoLocationConstraint(
                    worker_a_id=leader,
                    worker_b_id=follower,
                    strictness=strictness
                )
                registry.register(constraint)

        logger.info(
            "Registry built. Configuration: MaxHours=%s, MinRest=%s, "
            "Dynamic Rules=%d",
            self.max_hours_per_week,
            self.min_rest_hours,
            len(self.mutual_exclusions) + len(self.colocations)
        )

        return registry