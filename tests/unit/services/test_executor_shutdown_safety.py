"""Unit tests for ProcessPoolExecutor shutdown safety in solver_service."""

from __future__ import annotations

import sys
import types

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


def test_initialize_solver_worker_applies_memory_limit_when_resource_is_available(
    monkeypatch,
):
    calls: list[tuple[int, tuple[int, int]]] = []
    fake_resource = types.SimpleNamespace(
        RLIMIT_AS=1,
        RLIM_INFINITY=-1,
        getrlimit=lambda _limit: (-1, -1),
        setrlimit=lambda limit, values: calls.append((limit, values)),
    )

    monkeypatch.setitem(sys.modules, "resource", fake_resource)

    solver_service._initialize_solver_worker()

    assert calls, "Expected _initialize_solver_worker() to call resource.setrlimit()"
    limit, values = calls[0]
    assert limit == fake_resource.RLIMIT_AS
    assert values[0] == solver_service.SOLVER_PROCESS_MEMORY_LIMIT_MB * 1024 * 1024


def test_initialize_solver_worker_noops_when_resource_module_is_missing(monkeypatch):
    monkeypatch.delitem(sys.modules, "resource", raising=False)

    import builtins

    original_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "resource":
            raise ImportError("resource unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)

    solver_service._initialize_solver_worker()
