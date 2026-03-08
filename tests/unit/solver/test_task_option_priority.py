"""Unit tests for task option prioritization: domain, parser, constraint, and serialization.

Tests cover:
- Category 1: Parser (priority syntax, legacy OR, pipe splitting)
- Category 2: Domain model (priority field validation)
- Category 3: Constraint math (Y-var coefficients, solver preference)
- Category 4: Violation reporting
- Category 5: Registration & factory
- Category 6: Serialization round-trip
"""

import datetime as dt
from unittest.mock import MagicMock

import pytest
from ortools.linear_solver import pywraplp

from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from solver.constraints.base import SolverContext
from solver.constraints.static_soft import TaskOptionPriorityConstraint
from domain.time_utils import TimeWindow


pytestmark = [pytest.mark.unit]


# ========================================================================
# Helpers
# ========================================================================

def _build_priority_context(
    priorities: list[int] | None = None,
    preference_scores: list[int] | None = None,
) -> tuple[SolverContext, list[pywraplp.Variable]]:
    """Build a minimal SolverContext with one shift, one task, and N options.

    Args:
        priorities: Priority for each option. Defaults to [1, 3].
        preference_scores: Preference score for each option. Defaults to [0, 0].

    Returns:
        Tuple of (SolverContext, list of Y variables).
    """
    if priorities is None:
        priorities = [1, 3]
    if preference_scores is None:
        preference_scores = [0] * len(priorities)

    solver = pywraplp.Solver.CreateSolver("SCIP")
    assert solver is not None
    solver.Objective().SetMaximization()

    shift_start = dt.datetime(2024, 1, 1, 8, 0, 0)
    shift_end = shift_start + dt.timedelta(hours=8)
    shift = Shift(
        name="Priority Shift",
        shift_id="S1",
        time_window=TimeWindow(shift_start, shift_end),
    )

    task = Task(name="Kitchen", task_id="T1")
    y_vars_list = []
    y_vars_dict = {}
    task_metadata = {}

    for idx, (prio, pref) in enumerate(zip(priorities, preference_scores)):
        option = TaskOption(priority=prio, preference_score=pref)
        option.add_requirement(count=1, required_skills={"Skill": idx + 1})
        task.add_option(option)

        y_var = solver.IntVar(0, 1, f"Y_S1_T1_{idx}")
        y_vars_list.append(y_var)
        y_vars_dict[("S1", "T1", idx)] = y_var
        task_metadata[("S1", "T1", idx)] = option.requirements

        # Set existing preference_score coefficient (mimics solver_engine.py:96-97)
        if pref != 0:
            solver.Objective().SetCoefficient(y_var, pref)

    shift.add_task(task)

    # Exactly one option must be chosen
    solver.Add(sum(y_vars_list) == 1)

    context = SolverContext(
        solver=solver,
        x_vars={},
        y_vars=y_vars_dict,
        shifts=[shift],
        workers=[],
        worker_shift_assignments={},
        worker_global_assignments={},
        task_metadata=task_metadata,
    )
    return context, y_vars_list


# ========================================================================
# Category 1 — Parser Tests
# ========================================================================

class TestParserPrioritySyntax:
    """Tests for #X: priority parsing in ex_parser._parse_complex_task_string."""

    def _make_parser(self):
        """Create a minimal ExcelParser with mock repos."""
        from data.ex_parser import ExcelParser
        return ExcelParser(
            worker_repo=MagicMock(),
            shift_repo=MagicMock(),
        )

    def test_parse_priority_syntax_creates_correct_priorities(self):
        """#1: [Chef:5] x 1 #2: [Cook:3] x 1 -> 2 options, priorities 1 and 2."""
        parser = self._make_parser()
        task = Task("Test Task")
        parser._parse_complex_task_string(task, "#1: [Chef:5] x 1 #2: [Cook:3] x 1")

        assert len(task.options) == 2
        assert task.options[0].priority == 1
        assert task.options[1].priority == 2
        assert task.options[0].requirements[0].required_skills == {"Chef": 5}
        assert task.options[1].requirements[0].required_skills == {"Cook": 3}

    def test_parse_legacy_or_assigns_priority_1_and_warns(self):
        """OR syntax -> all priority=1, deprecation warning emitted."""
        parser = self._make_parser()
        task = Task("OR Task")
        parser._parse_complex_task_string(task, "[Chef:5] x 1 OR [Cook:3] x 1")

        assert len(task.options) == 2
        assert all(opt.priority == 1 for opt in task.options)
        assert any("legacy" in w.lower() or "OR" in w for w in parser._warnings)

    def test_parse_single_option_default_priority_1(self):
        """Single option without OR or #X: -> priority=1."""
        parser = self._make_parser()
        task = Task("Single Task")
        parser._parse_complex_task_string(task, "[Chef:5] x 1")

        assert len(task.options) == 1
        assert task.options[0].priority == 1

    def test_parse_no_hash_1_emits_warning(self):
        """#2: ... #3: ... with no #1 -> warning about missing #1."""
        parser = self._make_parser()
        task = Task("Missing #1")
        parser._parse_complex_task_string(task, "#2: [Chef:5] x 1 #3: [Cook:3] x 1")

        assert len(task.options) == 2
        assert task.options[0].priority == 2
        assert task.options[1].priority == 3
        assert any("#1" in w for w in parser._warnings)

    def test_parse_priority_out_of_range_clamped(self):
        """#0: -> clamped to 1, #7: -> clamped to 5."""
        parser = self._make_parser()
        task = Task("Clamped Task")
        parser._parse_complex_task_string(task, "#0: [Chef:5] x 1 #7: [Cook:3] x 1")

        assert len(task.options) == 2
        assert task.options[0].priority == 1
        assert task.options[1].priority == 5
        assert len(parser._warnings) >= 2  # two clamping warnings

    def test_parse_priority_plus_simultaneous_reqs(self):
        """#1: [Chef:5] x 1 + [Cook:3] x 2 -> 1 option, 2 requirements."""
        parser = self._make_parser()
        task = Task("Multi-Req Task")
        parser._parse_complex_task_string(task, "#1: [Chef:5] x 1 + [Cook:3] x 2")

        assert len(task.options) == 1
        assert task.options[0].priority == 1
        assert len(task.options[0].requirements) == 2
        assert task.options[0].requirements[0].count == 1
        assert task.options[0].requirements[1].count == 2

    def test_parse_pipe_creates_multiple_tasks(self):
        """Pipe splitting creates multiple Task objects on a shift."""
        from data.ex_parser import ExcelParser
        parser = ExcelParser(
            worker_repo=MagicMock(),
            shift_repo=MagicMock(),
        )
        shift = Shift(
            "Test Shift",
            time_window=TimeWindow(
                dt.datetime(2024, 1, 1, 8, 0),
                dt.datetime(2024, 1, 1, 16, 0),
            ),
        )

        raw_task = "[Chef:5] x 1 | [Waiter:3] x 2"
        task_segments = [seg.strip() for seg in raw_task.split('|') if seg.strip()]
        for idx, segment in enumerate(task_segments):
            task_container = Task(f"Task_{shift.shift_id}_{idx}")
            parser._parse_complex_task_string(task_container, segment)
            if task_container.options:
                shift.add_task(task_container)

        assert len(shift.tasks) == 2
        assert shift.tasks[0].options[0].requirements[0].required_skills == {"Chef": 5}
        assert shift.tasks[1].options[0].requirements[0].required_skills == {"Waiter": 3}


# ========================================================================
# Category 2 — Domain Model Tests
# ========================================================================

class TestTaskOptionDomain:
    """Tests for TaskOption.priority field validation."""

    def test_task_option_priority_default_is_1(self):
        """Default priority must be 1."""
        option = TaskOption()
        assert option.priority == 1

    def test_task_option_priority_valid_range(self):
        """Priorities 1-5 must be accepted."""
        for p in range(1, 6):
            option = TaskOption(priority=p)
            assert option.priority == p

    def test_task_option_priority_zero_raises(self):
        """Priority 0 must raise ValueError."""
        with pytest.raises(ValueError, match="1-5"):
            TaskOption(priority=0)

    def test_task_option_priority_six_raises(self):
        """Priority 6 must raise ValueError."""
        with pytest.raises(ValueError, match="1-5"):
            TaskOption(priority=6)

    def test_task_option_priority_negative_raises(self):
        """Negative priority must raise ValueError."""
        with pytest.raises(ValueError, match="1-5"):
            TaskOption(priority=-1)


# ========================================================================
# Category 3 — Constraint Math Tests
# ========================================================================

class TestConstraintMath:
    """Tests verifying correct Y-var coefficient manipulation."""

    def test_priority_1_no_penalty(self):
        """Y var coefficient for priority=1 must be unchanged (0)."""
        context, y_vars = _build_priority_context(priorities=[1, 1])
        constraint = TaskOptionPriorityConstraint(base_penalty=-20.0)
        constraint.apply(context)

        obj = context.solver.Objective()
        assert obj.GetCoefficient(y_vars[0]) == pytest.approx(0.0)
        assert obj.GetCoefficient(y_vars[1]) == pytest.approx(0.0)

    def test_priority_3_incurs_2x_base_penalty(self):
        """Priority 3 incurs penalty = base_penalty * (3 - 1) = 2x."""
        context, y_vars = _build_priority_context(priorities=[1, 3])
        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)

        obj = context.solver.Objective()
        assert obj.GetCoefficient(y_vars[0]) == pytest.approx(0.0)
        assert obj.GetCoefficient(y_vars[1]) == pytest.approx(-100.0)

    def test_priority_5_incurs_4x_base_penalty(self):
        """Priority 5 incurs penalty = base_penalty * (5 - 1) = 4x."""
        context, y_vars = _build_priority_context(priorities=[1, 5])
        constraint = TaskOptionPriorityConstraint(base_penalty=-10.0)
        constraint.apply(context)

        obj = context.solver.Objective()
        assert obj.GetCoefficient(y_vars[1]) == pytest.approx(-40.0)

    def test_additive_with_preference_score(self):
        """Penalty composes additively with existing preference_score coefficient."""
        context, y_vars = _build_priority_context(
            priorities=[1, 2],
            preference_scores=[10, 15],
        )
        constraint = TaskOptionPriorityConstraint(base_penalty=-20.0)

        # Before apply: coefficients are the preference scores
        obj = context.solver.Objective()
        assert obj.GetCoefficient(y_vars[0]) == pytest.approx(10.0)
        assert obj.GetCoefficient(y_vars[1]) == pytest.approx(15.0)

        constraint.apply(context)

        # After apply: priority=1 unchanged, priority=2 gets base_penalty * 1
        assert obj.GetCoefficient(y_vars[0]) == pytest.approx(10.0)
        assert obj.GetCoefficient(y_vars[1]) == pytest.approx(15.0 + (-20.0))

    def test_solver_prefers_priority_1_over_3(self):
        """When both options are feasible, solver picks #1 (higher total score)."""
        context, y_vars = _build_priority_context(priorities=[1, 3])
        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)

        status = context.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)

        # Option A (priority 1, coeff 0) should be selected over B (priority 3, coeff -100)
        assert y_vars[0].solution_value() == pytest.approx(1.0)
        assert y_vars[1].solution_value() == pytest.approx(0.0)

    def test_forced_selection_objective_value(self):
        """Forcing selection of priority=3 gives exact penalty in objective."""
        context, y_vars = _build_priority_context(priorities=[1, 3])
        context.solver.Add(y_vars[0] == 0)
        context.solver.Add(y_vars[1] == 1)

        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)

        status = context.solver.Solve()
        assert status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE)
        assert context.solver.Objective().Value() == pytest.approx(-100.0)


# ========================================================================
# Category 4 — Violation Reporting Tests
# ========================================================================

class TestViolationReporting:
    """Tests for get_violations() after solve."""

    def test_violations_report_selected_non_priority_1(self):
        """Selected #3 option should produce a violation."""
        context, y_vars = _build_priority_context(priorities=[1, 3])
        context.solver.Add(y_vars[0] == 0)
        context.solver.Add(y_vars[1] == 1)

        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)
        context.solver.Solve()

        violations = constraint.get_violations(context)
        assert len(violations) == 1
        assert violations[0].penalty == pytest.approx(-100.0)
        assert violations[0].observed_value == pytest.approx(3.0)
        assert violations[0].limit_value == pytest.approx(1.0)
        assert "priority #3" in violations[0].description.lower()

    def test_violations_empty_when_priority_1_selected(self):
        """No violations when the #1 option is selected."""
        context, y_vars = _build_priority_context(priorities=[1, 3])
        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)
        context.solver.Solve()

        violations = constraint.get_violations(context)
        assert len(violations) == 0

    def test_violations_empty_when_all_priority_1(self):
        """No violations when all options are priority 1."""
        context, y_vars = _build_priority_context(priorities=[1, 1])
        constraint = TaskOptionPriorityConstraint(base_penalty=-50.0)
        constraint.apply(context)
        context.solver.Solve()

        violations = constraint.get_violations(context)
        assert len(violations) == 0


# ========================================================================
# Category 5 — Registration & Factory Tests
# ========================================================================

class TestRegistrationAndFactory:
    """Tests for constraint_definitions registry integration."""

    def test_registered_in_definitions(self):
        """task_option_priority must be in the constraint_definitions registry."""
        from solver.constraints.definitions import (
            constraint_definitions,
            register_core_constraints,
        )
        try:
            register_core_constraints()
        except ValueError:
            pass  # Already registered

        defn = constraint_definitions.get("task_option_priority")
        assert defn is not None
        assert defn.key == "task_option_priority"
        assert defn.label == "Task option priority"

    def test_factory_creates_with_custom_penalty(self):
        """Factory must produce constraint with the configured base_penalty."""
        from solver.constraints.definitions import (
            constraint_definitions,
            register_core_constraints,
            TaskOptionPriorityConfig,
        )
        try:
            register_core_constraints()
        except ValueError:
            pass

        defn = constraint_definitions.get("task_option_priority")
        cfg = TaskOptionPriorityConfig(base_penalty=-35.0)
        instance = defn.factory(cfg)

        assert isinstance(instance, TaskOptionPriorityConstraint)
        assert instance.base_penalty == pytest.approx(-35.0)

    def test_factory_uses_default_penalty(self):
        """Factory with default config produces base_penalty=-20.0."""
        from solver.constraints.definitions import (
            constraint_definitions,
            register_core_constraints,
            TaskOptionPriorityConfig,
        )
        try:
            register_core_constraints()
        except ValueError:
            pass

        defn = constraint_definitions.get("task_option_priority")
        cfg = TaskOptionPriorityConfig()
        instance = defn.factory(cfg)

        assert instance.base_penalty == pytest.approx(-20.0)


# ========================================================================
# Category 6 — Serialization Round-Trip Tests
# ========================================================================

class TestSerializationRoundTrip:
    """Tests for priority field persistence in sql_shift_repo JSON."""

    def test_priority_survives_serialize_deserialize(self):
        """Priority 3 must survive serialize -> deserialize round-trip."""
        from repositories.sql_shift_repo import SQLShiftRepository

        task = Task(name="RT Task", task_id="T1")
        opt = TaskOption(priority=3)
        opt.add_requirement(count=1, required_skills={"Chef": 5})
        task.add_option(opt)

        # Use a detached repo instance just for serialization methods
        repo = SQLShiftRepository.__new__(SQLShiftRepository)
        serialized = repo._serialize_tasks_from_domain([task])
        deserialized = repo._deserialize_tasks_to_domain(serialized)

        assert len(deserialized) == 1
        assert len(deserialized[0].options) == 1
        assert deserialized[0].options[0].priority == 3

    def test_legacy_data_defaults_to_priority_1(self):
        """JSON without 'priority' key must default to priority 1."""
        from repositories.sql_shift_repo import SQLShiftRepository

        legacy_json = {
            "tasks": [{
                "task_id": "T1",
                "name": "Legacy Task",
                "options": [{
                    "preference_score": 0,
                    "requirements": [{"count": 1, "required_skills": {"Cook": 3}}],
                    # Note: no "priority" key
                }]
            }]
        }

        repo = SQLShiftRepository.__new__(SQLShiftRepository)
        deserialized = repo._deserialize_tasks_to_domain(legacy_json)

        assert len(deserialized) == 1
        assert deserialized[0].options[0].priority == 1

    def test_multiple_priorities_preserved(self):
        """Multiple options with different priorities survive round-trip."""
        from repositories.sql_shift_repo import SQLShiftRepository

        task = Task(name="Multi Task", task_id="T1")
        for p in [1, 2, 4]:
            opt = TaskOption(priority=p)
            opt.add_requirement(count=1, required_skills={"S": p})
            task.add_option(opt)

        repo = SQLShiftRepository.__new__(SQLShiftRepository)
        serialized = repo._serialize_tasks_from_domain([task])
        deserialized = repo._deserialize_tasks_to_domain(serialized)

        result_priorities = [o.priority for o in deserialized[0].options]
        assert result_priorities == [1, 2, 4]
