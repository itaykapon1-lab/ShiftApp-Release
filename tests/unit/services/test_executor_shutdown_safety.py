"""Unit tests for ProcessPoolExecutor shutdown safety in solver_service."""

from __future__ import annotations

import pytest

import services.solver_service as solver_service


class _FakeExecutor:
    def __init__(self):
        self.shutdown_calls: list[bool] = []

    def shutdown(self, wait: bool = True):
        self.shutdown_calls.append(wait)


class _RaisingExecutor:
    def shutdown(self, wait: bool = True):
        raise RuntimeError("teardown failure")


@pytest.fixture
def _reset_executor_state():
    original_executor = solver_service._executor
    solver_service._executor = None
    try:
        yield
    finally:
        solver_service._executor = original_executor


def test_shutdown_executor_cleans_global_reference_and_is_idempotent(
    monkeypatch,
    _reset_executor_state,
):
    created: list[_FakeExecutor] = []

    def _fake_constructor(*_args, **_kwargs):
        executor = _FakeExecutor()
        created.append(executor)
        return executor

    monkeypatch.setattr(
        solver_service.concurrent.futures,
        "ProcessPoolExecutor",
        _fake_constructor,
    )

    executor = solver_service.get_executor()
    assert executor is created[0]
    assert solver_service._executor is executor

    solver_service._shutdown_executor()
    assert executor.shutdown_calls == [True]
    assert solver_service._executor is None

    # Must not crash on repeated teardown calls.
    solver_service._shutdown_executor()
    assert executor.shutdown_calls == [True]
    assert solver_service._executor is None


def test_shutdown_executor_handles_teardown_exceptions_and_clears_reference(
    _reset_executor_state,
):
    solver_service._executor = _RaisingExecutor()

    # Strict contract: teardown failures must be contained.
    solver_service._shutdown_executor()

    assert solver_service._executor is None

    # Must remain safe on repeated teardown calls.
    solver_service._shutdown_executor()
    assert solver_service._executor is None
