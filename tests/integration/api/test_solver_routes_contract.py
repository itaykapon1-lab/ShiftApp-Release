"""API contract tests for solver routes."""

from unittest.mock import patch

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.contract]


def test_solve_route_returns_job_id(client):
    with patch("services.solver_service.SolverService.start_job", return_value="job-123"):
        response = client.post("/api/v1/solve")
    assert response.status_code == 200
    assert response.json() == {"job_id": "job-123"}


def test_status_route_not_found_for_unknown_job(client):
    with patch("services.solver_service.SolverService.get_job_status", return_value=None):
        response = client.get("/api/v1/status/unknown-job")
    assert response.status_code == 404

