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


def test_result_tool_recovery_prefers_call_id_over_same_name_ordinal(monkeypatch) -> None:
    appended: list[dict] = []
    monkeypatch.setattr(session_service, "load_conversation_events", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        session_service,
        "conversation_turn_items_from_events",
        lambda *_args, **_kwargs: [{
            "kind": "tool_call",
            "toolName": "grep_search_tool",
            "callId": "call-existing",
        }],
    )
    monkeypatch.setattr(
        session_service,
        "_append_session_conversation_event",
        lambda *_args, **kwargs: appended.append(kwargs),
    )

    persist._append_missing_canonical_result_items(
        "session-1",
        "turn-1",
        {
            "toolCalls": [
                {"name": "grep_search_tool", "callId": "call-new", "status": "completed", "result": "new"},
                {"name": "grep_search_tool", "callId": "call-existing", "status": "completed", "result": "old"},
            ],
        },
    )

    assert [item["payload"]["callId"] for item in appended] == ["call-new"]


def test_latest_client_submission_id_follows_the_current_user_turn() -> None:
    messages = [
        {"role": "user", "metadata": {"turnId": "turn-old", "clientSubmissionId": "submission-old"}},
        {"role": "user", "metadata": {"turnId": "turn-live", "clientSubmissionId": "submission-live"}},
    ]

    assert persist._latest_client_submission_id(messages, "turn-live") == "submission-live"
