from datetime import datetime

from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.worker_model import Worker
from solver.constraints.base import ConstraintType, SolverContext
from solver.constraints.dynamic import CoLocationConstraint, MutualExclusionConstraint
from solver.constraints.registry import ConstraintRegistry
from domain.time_utils import TimeWindow


def _build_context(assign_a: int, assign_b: int, include_b_eligibility: bool = True) -> SolverContext:
    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None

    worker_a = Worker(name="Alice", worker_id="W_A")
    worker_b = Worker(name="Bob", worker_id="W_B")
    shift = Shift(
        shift_id="S_1",
        name="Morning",
        time_window=TimeWindow(
            start=datetime(2026, 2, 16, 8, 0, 0),
            end=datetime(2026, 2, 16, 16, 0, 0),
        ),
    )

    var_a = solver.IntVar(0, 1, "X_W_A_S_1")
    solver.Add(var_a == assign_a)

    worker_shift_assignments = {
        ("W_A", "S_1"): [var_a],
    }
    worker_global_assignments = {
        "W_A": [(shift, var_a)],
    }

    if include_b_eligibility:
        var_b = solver.IntVar(0, 1, "X_W_B_S_1")
        solver.Add(var_b == assign_b)
        worker_shift_assignments[("W_B", "S_1")] = [var_b]
        worker_global_assignments["W_B"] = [(shift, var_b)]

    return SolverContext(
        solver=solver,
        x_vars={},
        y_vars={},
        shifts=[shift],
        workers=[worker_a, worker_b],
        worker_shift_assignments=worker_shift_assignments,
        worker_global_assignments=worker_global_assignments,
        task_metadata={},
    )


def test_mutual_exclusion_soft_emits_structured_violation():
    context = _build_context(assign_a=1, assign_b=1, include_b_eligibility=True)
    constraint = MutualExclusionConstraint(
        worker_a_id="W_A",
        worker_b_id="W_B",
        strictness=ConstraintType.SOFT,
        penalty=-100.0,
    )
    constraint.apply(context)
    context.solver.Objective().SetMaximization()
    status = context.solver.Solve()
    assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    violations = constraint.get_violations(context)
    assert len(violations) == 1
    violation = violations[0]
    assert violation.description.startswith("Worker ")
    assert violation.metadata is not None
    assert violation.metadata["rule_type"] == "mutual_exclusion"
    assert violation.metadata["worker_ids"] == ["W_A", "W_B"]
    assert violation.metadata["shift_id"] == "S_1"
    assert violation.penalty == -100.0


def test_colocation_soft_emits_violation_for_one_sided_eligibility():
    context = _build_context(assign_a=1, assign_b=0, include_b_eligibility=False)
    constraint = CoLocationConstraint(
        worker_a_id="W_A",
        worker_b_id="W_B",
        strictness=ConstraintType.SOFT,
        penalty=-50.0,
    )
    constraint.apply(context)
    context.solver.Objective().SetMaximization()
    status = context.solver.Solve()
    assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    violations = constraint.get_violations(context)
    assert len(violations) == 1
    violation = violations[0]
    assert "worked without required pair" in violation.description
    assert violation.metadata is not None
    assert violation.metadata["rule_type"] == "colocation"
    assert violation.metadata["primary_worker_id"] == "W_A"
    assert violation.metadata["paired_worker_id"] == "W_B"
    assert violation.metadata["shift_name"] == "Morning"


def test_registry_penalty_breakdown_includes_dynamic_metadata():
    context = _build_context(assign_a=1, assign_b=1, include_b_eligibility=True)
    registry = ConstraintRegistry()
    registry.register(
        MutualExclusionConstraint(
            worker_a_id="W_A",
            worker_b_id="W_B",
            strictness=ConstraintType.SOFT,
            penalty=-100.0,
        )
    )

    registry.apply_all(context)
    context.solver.Objective().SetMaximization()
    status = context.solver.Solve()
    assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

    breakdown = registry.get_penalty_breakdown(context)
    constraint_key = "ban_W_A_W_B"
    assert constraint_key in breakdown
    first_violation = breakdown[constraint_key]["violations"][0]
    assert first_violation["metadata"]["rule_type"] == "mutual_exclusion"
    assert first_violation["metadata"]["shift_id"] == "S_1"
