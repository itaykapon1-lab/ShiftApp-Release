"""API contract tests for configurable worker preference reward/penalty."""

import pytest

from solver.constraints.definitions import register_core_constraints


pytestmark = [pytest.mark.contract]


@pytest.fixture(autouse=True)
def _ensure_registry():
    """Ensure constraint definitions are registered before schema tests."""
    try:
        register_core_constraints()
    except ValueError:
        pass  # Already registered


def test_put_constraints_with_preference_params_persists_correctly(client, test_session_id):
    """PUT /constraints with preference_reward and preference_penalty persists correctly."""
    response = client.put(
        "/api/v1/constraints",
        json={
            "constraints": [
                {
                    "id": 1,
                    "category": "worker_preferences",
                    "type": "SOFT",
                    "enabled": True,
                    "params": {
                        "enabled": True,
                        "preference_reward": 25,
                        "preference_penalty": -50,
                    },
                }
            ]
        },
        cookies={"session_id": test_session_id},
    )
    assert response.status_code == 200

    get_response = client.get(
        "/api/v1/constraints",
        cookies={"session_id": test_session_id},
    )
    assert get_response.status_code == 200
    constraints = get_response.json()["constraints"]

    wp = next(c for c in constraints if c["category"] == "worker_preferences")
    assert wp["params"]["preference_reward"] == 25
    assert wp["params"]["preference_penalty"] == -50


def test_put_constraints_validates_preference_reward_lower_bound(client, test_session_id):
    """preference_reward < 1 must trigger 422."""
    response = client.put(
        "/api/v1/constraints",
        json={
            "constraints": [
                {
                    "id": 1,
                    "category": "worker_preferences",
                    "type": "SOFT",
                    "enabled": True,
                    "params": {
                        "enabled": True,
                        "preference_reward": 0,
                        "preference_penalty": -100,
                    },
                }
            ]
        },
        cookies={"session_id": test_session_id},
    )
    assert response.status_code == 422


def test_put_constraints_validates_preference_penalty_upper_bound(client, test_session_id):
    """preference_penalty > -1 must trigger 422."""
    response = client.put(
        "/api/v1/constraints",
        json={
            "constraints": [
                {
                    "id": 1,
                    "category": "worker_preferences",
                    "type": "SOFT",
                    "enabled": True,
                    "params": {
                        "enabled": True,
                        "preference_reward": 10,
                        "preference_penalty": 0,
                    },
                }
            ]
        },
        cookies={"session_id": test_session_id},
    )
    assert response.status_code == 422


def test_schema_includes_preference_reward_and_penalty_fields(client):
    """GET /constraints/schema must include the two new number fields for worker_preferences."""
    response = client.get("/api/v1/constraints/schema")
    assert response.status_code == 200

    schemas = response.json()
    wp_schema = next(s for s in schemas if s["key"] == "worker_preferences")

    field_names = [f["name"] for f in wp_schema["fields"]]
    assert "preference_reward" in field_names
    assert "preference_penalty" in field_names

    reward_field = next(f for f in wp_schema["fields"] if f["name"] == "preference_reward")
    assert reward_field["widget"] == "number"
    assert reward_field["default"] == 10

    penalty_field = next(f for f in wp_schema["fields"] if f["name"] == "preference_penalty")
    assert penalty_field["widget"] == "number"
    assert penalty_field["default"] == -100
