"""
Base definitions for the constraint system.

This module defines the fundamental protocols, data structures, and base classes
required to implement a pluggable constraint architecture. It decouples the
optimization logic from the core solver engine.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Protocol, Tuple, Optional, TYPE_CHECKING

from ortools.linear_solver import pywraplp

# Prevent circular imports for type hinting
if TYPE_CHECKING:
    from domain.shift_model import Shift
    from domain.worker_model import Worker


class ConstraintType(Enum):
    """Defines the strictness of a constraint."""
    HARD = "hard"      # Must be satisfied; violation renders solution infeasible.
    SOFT = "soft"      # Should be satisfied; violation incurs a penalty cost.


class ConstraintKind(Enum):
    """Defines the lifecycle and applicability of a constraint."""
    STATIC = "static"     # Applies unconditionally (e.g., max hours).
    DYNAMIC = "dynamic"   # Applies based on context (e.g., if X is assigned).


@dataclass
class SolverContext:
    """Encapsulates the mathematical and domain state required by constraints.

    This context acts as a bridge between the raw mathematical solver variables
    and the rich domain objects, allowing constraints to operate on business logic.

    Attributes:
        solver: The OR-Tools solver instance.
        x_vars: Map of assignment variables.
            Key: (worker_id, shift_id, task_id, role_signature)
            Value: Binary solver variable (1 if assigned, 0 otherwise).
        y_vars: Map of option selection variables.
            Key: (shift_id, task_id, option_index)
            Value: Binary solver variable (1 if option selected, 0 otherwise).
        shifts: List of all domain Shift objects in scope.
        workers: List of all domain Worker objects in scope.
        worker_shift_assignments: Index for intra-shift logic.
            Key: (worker_id, shift_id)
            Value: List of X variables for that worker in that specific shift.
        worker_global_assignments: Index for inter-shift logic.
            Key: worker_id
            Value: List of tuples (Shift, X_Variable) for all assignments.
    """
    solver: pywraplp.Solver
    x_vars: Dict[Tuple[str, str, str, Any], pywraplp.Variable]
    y_vars: Dict[Tuple[str, str, int], pywraplp.Variable]
    shifts: List['Shift']
    workers: List['Worker']
    worker_shift_assignments: Dict[Tuple[str, str], List[pywraplp.Variable]]
    worker_global_assignments: Dict[str, List[Tuple['Shift', pywraplp.Variable]]]
    task_metadata: Dict[Tuple[str, str, int], List[Any]]


@dataclass
class ConstraintViolation:
    """Represents a detailed report of a soft constraint violation.

    Attributes:
        constraint_name: The identifier of the constraint rule.
        description: Human-readable explanation (e.g., "Worker X exceeded max hours").
        penalty: The total cost added to the objective function for this specific violation.
        observed_value: The actual value measured (e.g., 45 hours).
        limit_value: The threshold that was crossed (e.g., 40 hours).
    """
    constraint_name: str
    description: str
    penalty: float
    observed_value: Optional[float] = None
    limit_value: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


class IConstraint(Protocol):
    """Interface that all scheduling constraints must implement."""

    @property
    def name(self) -> str:
        """Returns the unique identifier for this constraint."""
        ...

    @property
    def type(self) -> ConstraintType:
        """Returns whether the constraint is HARD or SOFT."""
        ...

    @property
    def kind(self) -> ConstraintKind:
        """Returns whether the constraint is STATIC or DYNAMIC."""
        ...

    @property
    def enabled(self) -> bool:
        """Returns True if the constraint should be applied."""
        ...

    def apply(self, context: SolverContext) -> None:
        """Applies the constraint logic to the solver context.

        For HARD constraints, this adds equations via solver.Add().
        For SOFT constraints, this adds variables and coefficients to the Objective.

        Args:
            context: The encapsulation of the current solver state.
        """
        ...

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """Calculates violations after the solver has found a solution.

        This is primarily used for reporting on SOFT constraints.

        Args:
            context: The context containing solved variable values.

        Returns:
            List[ConstraintViolation]: A list of specific violations found.
        """
        ...


class BaseConstraint:
    """Abstract base class providing common initialization for constraints.

    It is recommended to inherit from this class rather than implementing
    IConstraint directly to ensure consistent attribute handling.
    """

    def __init__(self,
                 name: str,
                 constraint_type: ConstraintType,
                 kind: ConstraintKind,
                 enabled: bool = True):
        """Initializes the base constraint attributes.

        Args:
            name (str): Unique identifier for the constraint.
            constraint_type (ConstraintType): HARD or SOFT.
            kind (ConstraintKind): STATIC or DYNAMIC.
            enabled (bool, optional): Whether the constraint is active. Defaults to True.
        """
        self._name = name
        self._type = constraint_type
        self._kind = kind
        self._enabled = enabled

    @property
    def name(self) -> str:
        return self._name

    @property
    def type(self) -> ConstraintType:
        return self._type

    @property
    def kind(self) -> ConstraintKind:
        return self._kind

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def apply(self, context: SolverContext) -> None:
        """Applies the constraint to the solver.

        Args:
            context (SolverContext): The solver state.

        Raises:
            NotImplementedError: Must be implemented by concrete subclasses.
        """
        raise NotImplementedError(f"Constraint {self.name} must implement apply()")

    def get_violations(self, context: SolverContext) -> List[ConstraintViolation]:
        """Retrieves violations for reporting purposes.

        Args:
            context (SolverContext): The solved state.

        Returns:
            List[ConstraintViolation]: Defaults to empty list. Override for soft constraints.
        """
        return []
