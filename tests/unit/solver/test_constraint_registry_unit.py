"""Unit tests for constraint registry behavior."""

from ortools.linear_solver import pywraplp
import pytest

from solver.constraints.base import BaseConstraint, ConstraintKind, ConstraintType, SolverContext
from solver.constraints.registry import ConstraintRegistry


pytestmark = [pytest.mark.unit]


class _DummyHard(BaseConstraint):
    def __init__(self, name, calls):
        super().__init__(name=name, constraint_type=ConstraintType.HARD, kind=ConstraintKind.STATIC, enabled=True)
        self.calls = calls

    def apply(self, context):
        self.calls.append(self.name)


def _ctx():
    solver = pywraplp.Solver("unit_registry", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)
    return SolverContext(
        solver=solver,
        x_vars={},
        y_vars={},
        shifts=[],
        workers=[],
        worker_shift_assignments={},
        worker_global_assignments={},
        task_metadata={},
    )


def test_registry_register_duplicate_raises():
    reg = ConstraintRegistry()
    calls = []
    reg.register(_DummyHard("dup", calls))
    with pytest.raises(ValueError):
        reg.register(_DummyHard("dup", calls))


def test_registry_apply_order_for_same_type_preserves_registration_order():
    reg = ConstraintRegistry()
    calls = []
    reg.register(_DummyHard("A", calls))
    reg.register(_DummyHard("B", calls))
    reg.apply_all(_ctx())
    assert calls == ["A", "B"]

