"""Unit tests for shift repository priority serialization/deserialization behavior."""

import pytest

from domain.task_model import TaskOption
from repositories.sql_shift_repo import SQLShiftRepository


pytestmark = [pytest.mark.unit]


def test_task_option_priority_zero_raises_value_error():
    with pytest.raises(ValueError):
        TaskOption(priority=0)


def test_deserialize_legacy_tasks_payload_defaults_missing_priority_to_one(
    db_session, test_session_id
):
    repo = SQLShiftRepository(db_session, test_session_id)
    legacy_payload = {
        "tasks": [
            {
                "task_id": "T_LEGACY",
                "name": "Legacy Task",
                "options": [
                    {
                        "preference_score": 0,
                        "requirements": [
                            {"count": 1, "required_skills": {"Chef": 5}},
                        ],
                    }
                ],
            }
        ]
    }

    tasks = repo._deserialize_tasks_to_domain(legacy_payload)
    assert len(tasks) == 1
    assert len(tasks[0].options) == 1
    assert tasks[0].options[0].priority == 1
