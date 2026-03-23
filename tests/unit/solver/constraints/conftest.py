"""Shared fixtures for isolated mathematical constraint testing.

Provides a `minimal_solver_context` factory that generates a lightweight
SolverContext with 2-3 workers, 2 shifts, and pre-built X/Y variables.
Each constraint test loads this context, applies ONE constraint, solves,
and verifies the mathematical effect in isolation.
"""

from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from domain.worker_model import Worker
from solver.constraints.base import SolverContext


# ---------------------------------------------------------------------------
# Canonical epoch time windows (matches the canonical week 2024-01-01..07)
# ---------------------------------------------------------------------------

MON_MORNING = TimeWindow(start=datetime(2024, 1, 1, 8, 0), end=datetime(2024, 1, 1, 16, 0))
MON_EVENING = TimeWindow(start=datetime(2024, 1, 1, 16, 0), end=datetime(2024, 1, 1, 23, 0))
TUE_MORNING = TimeWindow(start=datetime(2024, 1, 2, 8, 0), end=datetime(2024, 1, 2, 16, 0))

# Overlapping with MON_MORNING: starts at 12:00, ends at 20:00
MON_OVERLAP = TimeWindow(start=datetime(2024, 1, 1, 12, 0), end=datetime(2024, 1, 1, 20, 0))


# ---------------------------------------------------------------------------
# Factory: minimal_solver_context
# ---------------------------------------------------------------------------


def build_minimal_solver_context(
    workers: Optional[List[Worker]] = None,
    shifts: Optional[List[Shift]] = None,
    solver_id: str = "SCIP",
) -> SolverContext:
    """Build a minimal SolverContext with pre-created X and Y variables.

    Default setup:
        - 3 workers: Alice (Cook:5), Bob (Cook:5), Carol (Waiter:5)
        - 2 shifts: Monday Morning (8-16) with 1 task (Kitchen, needs 1 Cook)
                     Tuesday Morning (8-16) with 1 task (Service, needs 1 Waiter)
        - Y variables: one per task option (exactly-one constraint applied)
        - X variables: one per eligible (worker, shift, task, role) combination

    Args:
        workers: Override the default workers.
        shifts: Override the default shifts.
        solver_id: OR-Tools solver backend (default SCIP).

    Returns:
        SolverContext: Ready for constraint application and solving.
    """
    solver = pywraplp.Solver.CreateSolver(solver_id)
    assert solver is not None, f"Solver '{solver_id}' not available"

    # --- Default Workers ---
    if workers is None:
        workers = [
            Worker(
                worker_id="W_ALICE", name="Alice",
                skills={"Cook": 5},
                availability=[MON_MORNING, TUE_MORNING],
            ),
            Worker(
                worker_id="W_BOB", name="Bob",
                skills={"Cook": 5},
                availability=[MON_MORNING, TUE_MORNING],
            ),
            Worker(
                worker_id="W_CAROL", name="Carol",
                skills={"Waiter": 5},
                availability=[MON_MORNING, TUE_MORNING],
            ),
        ]

    # --- Default Shifts ---
    if shifts is None:
        kitchen_option = TaskOption(
            requirements=[Requirement(count=1, required_skills={"Cook": 1})],
            preference_score=0,
        )
        kitchen_task = Task(task_id="T_KITCHEN", name="Kitchen", options=[kitchen_option])

        service_option = TaskOption(
            requirements=[Requirement(count=1, required_skills={"Waiter": 1})],
            preference_score=0,
        )
        service_task = Task(task_id="T_SERVICE", name="Service", options=[service_option])

        shifts = [
            Shift(shift_id="S_MON_AM", name="Monday Morning", time_window=MON_MORNING, tasks=[kitchen_task]),
            Shift(shift_id="S_TUE_AM", name="Tuesday Morning", time_window=TUE_MORNING, tasks=[service_task]),
        ]

    # --- Build Variables ---
    y_vars: Dict[Tuple[str, str, int], pywraplp.Variable] = {}
    x_vars: Dict[Tuple[str, str, str, Tuple[str, ...]], pywraplp.Variable] = {}
    worker_global_assignments: Dict[str, List[Tuple[Shift, pywraplp.Variable]]] = defaultdict(list)
    worker_shift_assignments: Dict[Tuple[str, str], List[pywraplp.Variable]] = defaultdict(list)
    task_metadata: Dict[Tuple[str, str, int], List[Requirement]] = {}

    worker_map = {w.worker_id: w for w in workers}

    for shift in shifts:
        for task in shift.tasks:
            # Create Y variables (one per option)
            task_y_vars = []
            for opt_idx, option in enumerate(task.options):
                y_key = (shift.shift_id, task.task_id, opt_idx)
                y_var = solver.IntVar(0, 1, f"Y_{shift.shift_id}_{task.task_id}_{opt_idx}")
                y_vars[y_key] = y_var
                task_y_vars.append(y_var)

                # Store option preference in objective
                if option.preference_score != 0:
                    solver.Objective().SetCoefficient(y_var, option.preference_score)

                # Store task metadata for CoverageConstraint
                task_metadata[y_key] = option.requirements

            # Structural constraint: exactly one option per task
            if task_y_vars:
                solver.Add(sum(task_y_vars) == 1)

            # Create X variables for eligible workers
            processed_roles = set()
            for option in task.options:
                for req in option.requirements:
                    role_sig = tuple(sorted(req.required_skills.keys()))
                    if role_sig in processed_roles:
                        continue
                    processed_roles.add(role_sig)

                    for worker in workers:
                        # Check if worker has required skills
                        eligible = all(
                            worker.skills.get(sk, 0) >= lv
                            for sk, lv in req.required_skills.items()
                        )
                        # Check if worker is available during this shift
                        available = worker.is_available_for_shift(shift.time_window)

                        if eligible and available:
                            x_key = (worker.worker_id, shift.shift_id, task.task_id, role_sig)
                            if x_key not in x_vars:
                                x_var = solver.IntVar(
                                    0, 1,
                                    f"X_{worker.worker_id}_{shift.shift_id}_{task.task_id}_{hash(role_sig)}",
                                )
                                x_vars[x_key] = x_var
                                worker_global_assignments[worker.worker_id].append((shift, x_var))
                                worker_shift_assignments[(worker.worker_id, shift.shift_id)].append(x_var)

    return SolverContext(
        solver=solver,
        x_vars=x_vars,
        y_vars=y_vars,
        shifts=shifts,
        workers=workers,
        worker_shift_assignments=dict(worker_shift_assignments),
        worker_global_assignments=dict(worker_global_assignments),
        task_metadata=task_metadata,
    )


@pytest.fixture
def minimal_solver_context():
    """Pytest fixture returning the default minimal context factory."""
    return build_minimal_solver_context
