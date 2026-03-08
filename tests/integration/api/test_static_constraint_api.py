"""API persistence and validation tests for static constraint strictness."""

import pytest

from solver.constraints.definitions import register_core_constraints


pytestmark = [pytest.mark.integration, pytest.mark.contract]


@pytest.fixture(autouse=True)
def _ensure_constraint_registry():
    try:
        register_core_constraints()
    except ValueError:
        pass


def test_put_and_get_constraints_persist_static_hard_strictness(client, test_session_id):
    payload = {
        "constraints": [
            {
                "id": 101,
                "category": "max_hours_per_week",
                "type": "HARD",
                "enabled": True,
                "params": {
                    "max_hours": 35,
                    "penalty": 0.0,
                    "strictness": "HARD",
                },
            },
            {
                "id": 102,
                "category": "avoid_consecutive_shifts",
                "type": "HARD",
                "enabled": True,
                "params": {
                    "min_rest_hours": 12,
                    "penalty": 0.0,
                    "strictness": "HARD",
                },
            },
        ]
    }

    put_resp = client.put(
        "/api/v1/constraints",
        json=payload,
        cookies={"session_id": test_session_id},
    )
    assert put_resp.status_code == 200, put_resp.text

    get_resp = client.get(
        "/api/v1/constraints",
        cookies={"session_id": test_session_id},
    )
    assert get_resp.status_code == 200, get_resp.text

    by_category = {c["category"]: c for c in get_resp.json()["constraints"]}
    assert by_category["max_hours_per_week"]["type"] == "HARD"
    assert by_category["max_hours_per_week"]["params"]["strictness"] == "HARD"
    assert by_category["avoid_consecutive_shifts"]["type"] == "HARD"
    assert by_category["avoid_consecutive_shifts"]["params"]["strictness"] == "HARD"


@pytest.mark.parametrize(
    "category,params",
    [
        (
            "max_hours_per_week",
            {"max_hours": 40, "penalty": -10.0, "strictness": "SUPER_HARD"},
        ),
        (
            "avoid_consecutive_shifts",
            {"min_rest_hours": 12, "penalty": -30.0, "strictness": "SUPER_HARD"},
        ),
    ],
)
def test_put_constraints_rejects_invalid_static_strictness(
    client, test_session_id, category, params
):
    response = client.put(
        "/api/v1/constraints",
        json={
            "constraints": [
                {
                    "id": 201,
                    "category": category,
                    "type": "SOFT",
                    "enabled": True,
                    "params": params,
                }
            ]
        },
        cookies={"session_id": test_session_id},
    )

    assert response.status_code == 422
    assert "strictness" in str(response.json().get("detail", "")).lower()
