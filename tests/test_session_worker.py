"""Focused tests for session worker slice."""

from __future__ import annotations

from core.web.services import session_service
from core.web.services.session import worker


def test_facade_reexports_worker_entrypoints() -> None:
    assert session_service._run_session_turn is worker._run_session_turn
    assert session_service._run_session_continuation_loop is worker._run_session_continuation_loop
    assert (
        session_service._session_context_allows_internal_auto_continue
        is worker._session_context_allows_internal_auto_continue
    )


def test_internal_auto_continue_context_helpers() -> None:
    assert worker._session_context_allows_internal_auto_continue({}) is False
    assert worker._session_context_allows_internal_auto_continue(
        {"allow_internal_auto_continue": True}
    ) is True
    assert worker._session_context_internal_auto_continue_max_turns({}) == 3
    assert worker._session_context_internal_auto_continue_max_turns(
        {"max_internal_auto_continue_turns": 7}
    ) == 7


def test_run_session_turn_skips_stale_turn(monkeypatch) -> None:
    """Stale turn_id must exit without running agent."""

    calls: list[str] = []

    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: False)
    monkeypatch.setattr(
        session_service,
        "_record_session_turn_lifecycle_event",
        lambda *args, **kwargs: calls.append("lifecycle"),
    )
    monkeypatch.setattr(
        session_service,
        "_persist_session_turn_result",
        lambda *args, **kwargs: calls.append("persist"),
    )

    worker._run_session_turn(
        {
            "session_id": "worker-s1",
            "turn_id": "stale-turn",
            "user_message": "hello",
        }
    )
    assert "lifecycle" in calls
    assert "persist" not in calls
