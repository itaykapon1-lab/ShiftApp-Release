import logging
import pytest
from ortools.linear_solver import pywraplp

from solver.constraints.registry import ConstraintRegistry
from solver.constraints.base import BaseConstraint, ConstraintType, ConstraintKind, SolverContext, ConstraintViolation


# --- Helpers -----------------------------------------------------------------

def make_empty_context():
    # Use a simple LP solver since these tests don't add integer vars/constraints
    solver = pywraplp.Solver("registry_test", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)
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


class FakeHard(BaseConstraint):
    def __init__(self, name: str, call_log: list, enabled: bool = True):
        super().__init__(name=name, constraint_type=ConstraintType.HARD, kind=ConstraintKind.STATIC, enabled=enabled)
        self._log = call_log

    def apply(self, context: SolverContext) -> None:
        self._log.append(f"apply:{self.name}:HARD")

    def get_violations(self, context: SolverContext):
        return []


class FakeSoft(BaseConstraint):
    def __init__(self, name: str, call_log: list, violations=None, enabled: bool = True):
        super().__init__(name=name, constraint_type=ConstraintType.SOFT, kind=ConstraintKind.STATIC, enabled=enabled)
        self._log = call_log
        self._violations = list(violations or [])

    def apply(self, context: SolverContext) -> None:
        self._log.append(f"apply:{self.name}:SOFT")

    def get_violations(self, context: SolverContext):
        return [
            ConstraintViolation(
                constraint_name=self.name,
                description=v.get("description", ""),
                penalty=v.get("penalty", 0.0),
                observed_value=v.get("observed"),
                limit_value=v.get("limit"),
            )
            for v in self._violations
        ]


# --- Tests -------------------------------------------------------------------

# 1) Should apply all HARD constraints before SOFT constraints, preserving registration order per type

def test_apply_order_hard_before_soft():
    calls = []
    reg = ConstraintRegistry()

    # Interleave registration order
    reg.register(FakeHard("H1", calls))
    reg.register(FakeSoft("S1", calls))
    reg.register(FakeHard("H2", calls))
    reg.register(FakeSoft("S2", calls))

    ctx = make_empty_context()
    reg.apply_all(ctx)

    # Expect all HARD first (H1, H2) then SOFT (S1, S2)
    assert calls == [
        "apply:H1:HARD",
        "apply:H2:HARD",
        "apply:S1:SOFT",
        "apply:S2:SOFT",
    ]


# 2) Should skip disabled constraints during apply_all

def test_skip_disabled_constraints_on_apply():
    calls = []
    reg = ConstraintRegistry()

    reg.register(FakeHard("H_enabled", calls, enabled=True))
    reg.register(FakeHard("H_disabled", calls, enabled=False))
    reg.register(FakeSoft("S_enabled", calls, enabled=True))
    reg.register(FakeSoft("S_disabled", calls, enabled=False))

    ctx = make_empty_context()
    reg.apply_all(ctx)

    assert calls == [
        "apply:H_enabled:HARD",
        "apply:S_enabled:SOFT",
    ]


# 3) Should aggregate violations only from enabled soft constraints

def test_get_violations_only_from_enabled_soft():
    calls = []
    reg = ConstraintRegistry()

    v_soft = [
        {"description": "demo violation", "penalty": -1.0, "observed": 5, "limit": 4}
    ]

    reg.register(FakeHard("H1", calls, enabled=True))  # should not contribute violations
    reg.register(FakeSoft("S_ok", calls, violations=v_soft, enabled=True))
    reg.register(FakeSoft("S_disabled", calls, violations=v_soft, enabled=False))
    reg.register(FakeSoft("S_empty", calls, violations=[], enabled=True))

    ctx = make_empty_context()

    # No need to call apply_all to test aggregation behavior
    viols = reg.get_violations(ctx)

    assert set(viols.keys()) == {"S_ok"}
    assert len(viols["S_ok"]) == 1
    assert viols["S_ok"][0].description == "demo violation"


# 4) Should raise ValueError when registering duplicate constraint name

def test_register_duplicate_name_raises():
    reg = ConstraintRegistry()
    calls = []

    reg.register(FakeHard("dup", calls))
    with pytest.raises(ValueError):
        reg.register(FakeSoft("dup", calls))


# 5) Should add core constraints exactly once and avoid duplicates on repeated calls

def test_add_core_constraints_idempotent():
    reg = ConstraintRegistry()

    # Initial add
    reg.add_core_constraints()

    # Verify presence by name via internal list (test-only introspection)
    names = {c.name for c in getattr(reg, "_constraints", [])}
    assert {"coverage", "intra_shift_exclusivity", "overlap_prevention"}.issubset(names)

    first_count = len(getattr(reg, "_constraints", []))

    # Repeat should not duplicate or raise
    reg.add_core_constraints()
    second_count = len(getattr(reg, "_constraints", []))

    assert second_count == first_count


# 6) Should log a warning when enabling/disabling unknown constraint names

def test_enable_disable_unknown_logs_warning(caplog):
    reg = ConstraintRegistry()

    with caplog.at_level(logging.WARNING):
        reg.enable("unknown_rule")
        reg.disable("another_unknown")

    warnings = [rec.message for rec in caplog.records if rec.levelname == "WARNING"]
    assert any("unknown constraint" in msg.lower() for msg in warnings)
