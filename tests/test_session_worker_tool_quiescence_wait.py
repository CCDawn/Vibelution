"""Focused tests for the bounded tool-execution quiescence wait in session worker."""

from __future__ import annotations

import time
from concurrent.futures import Future
from threading import Timer
from typing import Any

import pytest

from core.infrastructure.tool_execution_scope import ToolExecutionScope
from core.web.services.session import worker


class _RecordingService:
    """Stand-in for the session_service facade's lifecycle event recorder."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def _record_session_turn_lifecycle_event(
        self, session_id: str, phase: str, **kwargs: Any
    ) -> None:
        self.events.append((phase, kwargs))

    def phases(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for phase, kwargs in self.events if phase == name]


@pytest.fixture()
def recording_service(monkeypatch: pytest.MonkeyPatch) -> _RecordingService:
    service = _RecordingService()
    monkeypatch.setattr(worker, "_service", lambda: service)
    return service


def _sealed_scope_with_pending_tool(tool_name: str = "grep") -> tuple[ToolExecutionScope, Future[str]]:
    scope = ToolExecutionScope(session_id="session-a", turn_id="turn-a")
    future: Future[str] = Future()
    scope.register(future, tool_name=tool_name)
    scope.seal()
    return scope, future


def test_quiescence_wait_is_silent_when_scope_already_quiescent(
    recording_service: _RecordingService,
) -> None:
    scope = ToolExecutionScope(session_id="session-a", turn_id="turn-a")
    scope.seal()

    worker._wait_for_tool_execution_quiescence(scope)

    assert recording_service.events == []


def test_quiescence_wait_finishes_once_pending_clears(
    recording_service: _RecordingService,
) -> None:
    scope, future = _sealed_scope_with_pending_tool()
    # Resolve the future while the first poll wait is still in flight: the
    # loop must return as soon as quiescence is observed, not wait for budget.
    started_at = time.monotonic()

    def settle() -> None:
        future.set_result("done")

    Timer(0.05, settle).start()
    worker._wait_for_tool_execution_quiescence(scope)
    elapsed = time.monotonic() - started_at

    assert scope.is_quiescent() is True
    assert recording_service.phases("tool_quiescence_wait_started")
    assert recording_service.phases("tool_quiescence_wait_finished")
    assert not recording_service.phases("tool_quiescence_wait_budget_exhausted")
    assert elapsed < worker.TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS


def test_quiescence_wait_gives_up_after_budget_and_keeps_teardown_going(
    recording_service: _RecordingService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope, _future = _sealed_scope_with_pending_tool("leaked_grep")
    monkeypatch.setattr(worker, "_tool_quiescence_wait_budget_seconds", lambda: 0.15)
    started_at = time.monotonic()

    worker._wait_for_tool_execution_quiescence(scope)
    elapsed = time.monotonic() - started_at

    assert recording_service.phases("tool_quiescence_wait_started")
    assert not recording_service.phases("tool_quiescence_wait_finished")
    exhausted = recording_service.phases("tool_quiescence_wait_budget_exhausted")
    assert exhausted, "budget abandonment must be observable in lifecycle events"
    fields = exhausted[0]["fields"]
    assert fields["sessionId"] == "session-a"
    assert fields["turnId"] == "turn-a"
    assert fields["pendingCount"] == 1
    assert fields["pendingTools"] == ["leaked_grep"]
    assert fields["budgetSeconds"] == pytest.approx(0.15, abs=1e-6)
    # The wait must stop well below the real 10s default budget.
    assert elapsed < 5.0
    # The scope is still not quiescent: the leaked tool future keeps pending,
    # but teardown already continued past the wait.
    assert scope.is_quiescent() is False


def test_quiescence_wait_budget_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIBELUTION_TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS", raising=False)
    assert worker._tool_quiescence_wait_budget_seconds() == (
        worker.TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS
    )
    assert worker.TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS == 10.0

    monkeypatch.setenv("VIBELUTION_TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS", "2.5")
    assert worker._tool_quiescence_wait_budget_seconds() == 2.5

    for invalid in ("0", "-3", "not-a-number"):
        monkeypatch.setenv("VIBELUTION_TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS", invalid)
        assert worker._tool_quiescence_wait_budget_seconds() == (
            worker.TOOL_QUIESCENCE_WAIT_BUDGET_SECONDS
        )
