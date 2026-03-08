"""Unit tests for Excel task parsing with task-option priorities."""

from datetime import datetime

import pandas as pd
import pytest

from data.ex_parser import ExcelParser
from domain.task_model import Task
from repositories.memory_repo import MemoryShiftRepository, MemoryWorkerRepository


pytestmark = [pytest.mark.unit]


def _make_parser() -> tuple[ExcelParser, MemoryShiftRepository]:
    worker_repo = MemoryWorkerRepository()
    shift_repo = MemoryShiftRepository()
    parser = ExcelParser(worker_repo=worker_repo, shift_repo=shift_repo)
    parser.start_date = datetime(2024, 1, 7)
    return parser, shift_repo


def _single_shift_df(tasks: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Day": "Monday",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Shift Name": "Priority Shift",
                "Tasks": tasks,
            }
        ]
    )


def test_pipe_split_creates_one_shift_with_two_distinct_tasks():
    parser, shift_repo = _make_parser()

    parser._process_shifts(_single_shift_df("[Chef:5] x 1 | [Cook:3] x 1"))

    shifts = shift_repo.get_all()
    assert len(shifts) == 1

    shift = shifts[0]
    assert len(shift.tasks) == 2
    assert shift.tasks[0].options[0].requirements[0].required_skills == {"Chef": 5}
    assert shift.tasks[1].options[0].requirements[0].required_skills == {"Cook": 3}


def test_priority_syntax_parses_explicit_option_priorities():
    parser, _ = _make_parser()
    task = Task(name="Kitchen")

    parser._parse_complex_task_string(task, "#1: [Chef:5] x 1 #3: [Cook:3] x 1")

    assert len(task.options) == 2
    assert [option.priority for option in task.options] == [1, 3]
    assert task.options[0].requirements[0].required_skills == {"Chef": 5}
    assert task.options[1].requirements[0].required_skills == {"Cook": 3}


def test_priority_greater_than_five_is_clamped_or_rejected():
    parser, _ = _make_parser()
    task = Task(name="Kitchen")

    try:
        parser._parse_complex_task_string(task, "#1: [Chef:5] x 1 #6: [Cook:3] x 1")
    except ValueError as exc:
        assert "priority" in str(exc).lower()
    else:
        assert len(task.options) == 2
        assert task.options[1].priority == 5


def test_priority_syntax_requires_at_least_one_priority_one():
    parser, _ = _make_parser()
    task = Task(name="Kitchen")

    parser._parse_complex_task_string(task, "#2: [Chef:5] x 1 #3: [Cook:3] x 1")

    assert len(task.options) == 2
    assert [option.priority for option in task.options] == [2, 3]
    assert any("#1" in warning for warning in parser._warnings)


def test_legacy_or_syntax_defaults_priorities_and_emits_warning():
    parser, _ = _make_parser()
    task = Task(name="Kitchen")

    parser._parse_complex_task_string(task, "[Chef:5] x 1 OR [Cook:3] x 1")

    assert len(task.options) == 2
    assert all(option.priority == 1 for option in task.options)
    assert any("or" in warning.lower() and "priority" in warning.lower() for warning in parser._warnings)
