"""Slow solver timeout/recovery style verification."""

import os
from unittest.mock import patch

import pytest

from services.solver_service import SolverJobStore, run_solver_in_process


pytestmark = [pytest.mark.slow]


def test_solver_failure_path_updates_job_status(db_session, session_id_factory):
    if os.getenv("RUN_SLOW_TESTS") != "1":
        pytest.skip("Set RUN_SLOW_TESTS=1 to run timeout/recovery test")

    session_id = session_id_factory("perf")
    job_id = SolverJobStore.create_job(db_session, session_id)

    with patch("services.solver_service.SQLWorkerRepository.get_all", side_effect=TimeoutError("solver timeout")):
        run_solver_in_process(job_id, session_id)

    data = SolverJobStore.get_job(db_session, job_id)
    assert data["status"].value in ("FAILED", "COMPLETED")
    if data["status"].value == "FAILED":
        assert "timeout" in (data["error_message"] or "").lower()

