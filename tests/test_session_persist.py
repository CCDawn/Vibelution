"""Focused tests for session persist slice."""

from __future__ import annotations

from core.web.services import session_service
from core.web.services.session import persist


def test_facade_reexports_persist_entrypoints() -> None:
    assert session_service._persist_session_turn_result is persist._persist_session_turn_result
    assert session_service._persist_session_turn_failure is persist._persist_session_turn_failure
    assert session_service._persist_session_turn_runtime_error is persist._persist_session_turn_runtime_error
    assert (
        session_service._ensure_session_turn_terminal_fallback
        is persist._ensure_session_turn_terminal_fallback
    )


def test_persist_turn_result_noop_when_conversation_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(session_service, "load_chat_state", lambda _root: {"conversations": []})
    monkeypatch.setattr(session_service, "_find_conversation_entry", lambda payload, sid: None)

    # Must return without raising when conversation is gone.
    persist._persist_session_turn_result(
        "missing-session",
        {"status": "completed", "summary": "ok", "raw_output": "ok"},
        turn_id="turn-x",
    )


def test_persist_turn_result_skips_stale_turn(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        session_service,
        "load_chat_state",
        lambda _root: {"conversations": [{"id": "s1"}]},
    )
    monkeypatch.setattr(
        session_service,
        "_find_conversation_entry",
        lambda payload, sid: {"id": sid},
    )
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: False)
    called: list[str] = []
    monkeypatch.setattr(
        session_service,
        "_session_ledger_visible_messages",
        lambda sid: called.append("ledger") or [],
    )

    persist._persist_session_turn_result(
        "s1",
        {"status": "completed", "summary": "ok", "raw_output": "ok"},
        turn_id="stale",
    )
    assert called == []
