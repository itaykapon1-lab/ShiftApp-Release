"""Unit tests for Task/Requirement domain models."""

import pytest

from domain.task_model import Requirement, Task, TaskOption


pytestmark = [pytest.mark.unit]


def test_requirement_count_must_be_positive():
    with pytest.raises(ValueError):
        Requirement(count=0, required_skills={"Chef": 1})


def test_task_option_add_requirement():
    option = TaskOption()
    option.add_requirement(count=2, required_skills={"Chef": 5})
    assert len(option.requirements) == 1
    assert option.requirements[0].count == 2
    assert option.requirements[0].required_skills == {"Chef": 5}


def test_task_can_store_multiple_options():
    task = Task(name="Service")
    task.add_option(TaskOption(preference_score=0))
    task.add_option(TaskOption(preference_score=10))
    assert len(task.options) == 2

