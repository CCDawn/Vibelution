"""Focused tests for session persist slice."""

from __future__ import annotations

import threading

import pytest

from core.infrastructure import developer_sandbox
from core.ui.chat_state import load_session_chat_state, save_session_chat_state
from core.web.services import session_service
from core.web.services.session import persist
from tests.helpers.web_chat_state import _seed_chat_state


@pytest.fixture(autouse=True)
def _isolated_data_home(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path / "operator-data"))
    monkeypatch.setattr(developer_sandbox, "is_developer_mode_enabled", lambda: False)


def _chat_state_lock_held() -> bool:
    lock = session_service._CHAT_STATE_LOCK
    return bool(getattr(lock._local, "transactions", None))


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
    monkeypatch.setattr(session_service, "_is_session_turn_current", lambda sid, tid: True)
    monkeypatch.setattr(session_service, "load_session_chat_state", lambda _root, _sid: None)

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


def test_persist_turn_result_keeps_sibling_and_releases_lock_before_journal(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_chat_state(
        tmp_path,
        conversations=[
            {
                "conversation_id": "session-a",
                "title": "A",
                "last_turn_status": "running",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "go", "timestamp": "2026-05-18T11:55:00"}],
            },
            {
                "conversation_id": "session-b",
                "title": "B",
                "last_turn_status": "ready",
                "updated_at": "2026-05-18T12:00:00",
                "messages": [{"role": "user", "content": "idle", "timestamp": "2026-05-18T11:55:00"}],
            },
        ],
    )
    session_service._set_session_running("session-a", True, turn_id="turn-a")
    full_saves: list[str] = []
    original_save_chat_state = session_service.save_chat_state
    monkeypatch.setattr(
        session_service,
        "save_chat_state",
        lambda *args, **kwargs: full_saves.append("save") or original_save_chat_state(*args, **kwargs),
    )

    journal_started = threading.Event()
    sibling_saved = threading.Event()
    held_during_journal: list[bool] = []
    original_append = session_service._append_session_conversation_event

    def journal_after_lock(*args, **kwargs):
        held_during_journal.append(_chat_state_lock_held())
        journal_started.set()
        assert sibling_saved.wait(timeout=2.0)
        return original_append(*args, **kwargs)

    monkeypatch.setattr(session_service, "_append_session_conversation_event", journal_after_lock)

    errors: list[BaseException] = []

    def persist_a() -> None:
        try:
            persist._persist_session_turn_result(
                "session-a",
                {"status": "completed", "summary": "done", "raw_output": "done"},
                turn_id="turn-a",
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)

    persist_thread = threading.Thread(target=persist_a)
    persist_thread.start()
    assert journal_started.wait(timeout=5.0)
    save_session_chat_state(
        tmp_path,
        "session-b",
        {
            "conversation_id": "session-b",
            "title": "B",
            "last_turn_status": "running",
        },
    )
    sibling_saved.set()
    persist_thread.join(timeout=5.0)

    assert errors == []
    assert not persist_thread.is_alive()
    assert full_saves == []
    assert held_during_journal
    assert held_during_journal == [False] * len(held_during_journal)
    assert load_session_chat_state(tmp_path, "session-a")["last_turn_status"] == "ready"
    assert load_session_chat_state(tmp_path, "session-b")["last_turn_status"] == "running"
    assert load_session_chat_state(tmp_path, "session-b")["title"] == "B"


def test_commit_session_turn_runtime_state_preserves_concurrent_same_session_fields(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_session_chat_state(
        tmp_path,
        "session-a",
        {
            "conversation_id": "session-a",
            "title": "Before",
            "last_turn_status": "running",
            "last_turn_error": {"message": "old"},
        },
    )
    previous = load_session_chat_state(tmp_path, "session-a")
    assert previous is not None
    desired = dict(previous)
    desired["last_turn_status"] = "ready"
    desired.pop("last_turn_error", None)

    save_session_chat_state(
        tmp_path,
        "session-a",
        {
            **previous,
            "title": "Renamed concurrently",
            "operatorNote": "keep",
        },
    )

    assert persist._commit_session_turn_runtime_state(
        "session-a",
        desired,
        previous_conversation=previous,
    ) is True
    stored = load_session_chat_state(tmp_path, "session-a")
    assert stored is not None
    assert stored["title"] == "Renamed concurrently"
    assert stored["operatorNote"] == "keep"
    assert stored["last_turn_status"] == "ready"
    assert "last_turn_error" not in stored


_PAYLOAD_PROTOCOL_ERROR = "payload_protocol_error: duplicate tool call id"


def _seed_running_session(tmp_path, session_id: str, turn_id: str) -> None:
    save_session_chat_state(
        tmp_path,
        session_id,
        {
            "conversation_id": session_id,
            "title": "T",
            "last_turn_status": "running",
            "updated_at": "2026-08-27T12:00:00",
        },
    )
    session_service._set_session_running(session_id, True, turn_id=turn_id)


def test_persist_turn_result_provider_protocol_error_keeps_error_out_of_journal(
    tmp_path,
    monkeypatch,
) -> None:
    """A payload-protocol failure is turn metadata, never model-visible dialogue."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_running_session(tmp_path, "session-a", "turn-a")

    persist._persist_session_turn_result(
        "session-a",
        {
            "status": "failed",
            "summary": _PAYLOAD_PROTOCOL_ERROR,
            "raw_output": _PAYLOAD_PROTOCOL_ERROR,
            "error": _PAYLOAD_PROTOCOL_ERROR,
        },
        turn_id="turn-a",
    )

    events = session_service._load_session_conversation_events_cached("session-a")
    assistant_events = [event for event in events if event.event_type == session_service.EVENT_ASSISTANT_MESSAGE]
    assert assistant_events == []
    failed_events = [event for event in events if event.event_type == session_service.EVENT_TURN_FAILED]
    assert len(failed_events) == 1
    assert failed_events[0].payload.get("errorType") == "provider_protocol_error"
    assert "duplicate tool call id" in str(failed_events[0].payload.get("rawError") or "")
    from core.chat.turn_journal import event_has_model_projection

    model_visible_text = " ".join(
        str((event.payload or {}).get("content") or (event.payload or {}).get("text") or "")
        for event in events
        if event_has_model_projection(event)
    )
    assert "payload_protocol_error" not in model_visible_text

    stored = load_session_chat_state(tmp_path, "session-a")
    assert stored is not None
    assert stored.get("last_turn_status") == "failed"
    assert stored.get("last_turn_error")


def test_persist_turn_result_provider_failure_allows_next_turn_reconcile(
    tmp_path,
    monkeypatch,
) -> None:
    """After a clean provider-failure persist, the next turn's seed matches the ledger."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_running_session(tmp_path, "session-a", "turn-a")
    session_service._append_session_conversation_event(
        "session-a",
        "turn-a",
        session_service.EVENT_USER_MESSAGE,
        status="recorded",
        payload={"role": "user", "content": "执行资料搜集任务", "turnId": "turn-a"},
        source="submit_session_message",
    )

    persist._persist_session_turn_result(
        "session-a",
        {
            "status": "failed",
            "summary": _PAYLOAD_PROTOCOL_ERROR,
            "raw_output": _PAYLOAD_PROTOCOL_ERROR,
            "error": _PAYLOAD_PROTOCOL_ERROR,
        },
        turn_id="turn-a",
    )

    from core.chat.conversation_invariant import canonical_conversation_messages_from_events
    from core.infrastructure.runtime_input import build_chat_user_message
    from core.orchestration.turn_message_assembly import (
        reconcile_chat_messages_with_ledger,
        ledger_seeded_history_fingerprint,
    )

    events = session_service._load_session_conversation_events_cached("session-a")
    historical = canonical_conversation_messages_from_events(events, current_turn_id="turn-b")
    assert historical, "seed history must survive a failed turn"
    assert all("payload_protocol_error" not in str(item.get("content") or "") for item in historical)

    seeded = [
        build_chat_user_message("执行资料搜集任务"),
        build_chat_user_message("继续下一步"),
    ]
    reconciled = reconcile_chat_messages_with_ledger(
        seeded,
        events,
        turn_id="turn-b",
        strict=True,
    )
    assert reconciled == seeded
    stamped = ledger_seeded_history_fingerprint(events, turn_id="turn-b")
    assert stamped


def test_journal_poisoning_assistant_message_breaks_next_turn_reconcile(
    tmp_path,
    monkeypatch,
) -> None:
    """Pin the poisoning mechanism: a raw-error assistant item fails reconciliation."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_running_session(tmp_path, "session-a", "turn-a")
    session_service._append_session_conversation_event(
        "session-a",
        "turn-a",
        session_service.EVENT_USER_MESSAGE,
        status="recorded",
        payload={"role": "user", "content": "执行资料搜集任务", "turnId": "turn-a"},
        source="submit_session_message",
    )
    # Simulate the production poisoning frame: raw error text committed as a
    # model-visible assistant message (journal seq 232 of the incident).
    session_service._append_session_conversation_event(
        "session-a",
        "turn-a",
        session_service.EVENT_ASSISTANT_MESSAGE,
        status="needs_continue",
        payload={"role": "assistant", "content": _PAYLOAD_PROTOCOL_ERROR},
        source="persist_session_turn_result",
    )

    from core.chat.conversation_invariant import canonical_conversation_messages_from_events
    from core.infrastructure.runtime_input import build_chat_user_message
    from core.orchestration.turn_message_assembly import TurnJournalReplayError, reconcile_chat_messages_with_ledger

    events = session_service._load_session_conversation_events_cached("session-a")
    historical = canonical_conversation_messages_from_events(events, current_turn_id="turn-b")
    assert any(_PAYLOAD_PROTOCOL_ERROR in str(item.get("content") or "") for item in historical)

    # The seed pipeline omits provider-error assistant text, so the seeded
    # history lacks the poisoned frame while the ledger reconstruction keeps
    # it — exactly the drift that produced the production incident.
    seeded = [
        build_chat_user_message("执行资料搜集任务"),
        build_chat_user_message("继续下一步"),
    ]
    with pytest.raises(TurnJournalReplayError) as exc_info:
        reconcile_chat_messages_with_ledger(seeded, events, turn_id="turn-b", strict=True)
    assert exc_info.value.error_type == "ledger_history_mismatch"


def test_persist_turn_result_completed_still_journals_assistant_message(
    tmp_path,
    monkeypatch,
) -> None:
    """The fix only diverts failures; successful replies keep their journal frame."""

    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _seed_running_session(tmp_path, "session-a", "turn-a")

    persist._persist_session_turn_result(
        "session-a",
        {"status": "completed", "summary": "已完成资料搜集。", "raw_output": "已完成资料搜集。"},
        turn_id="turn-a",
    )

    events = session_service._load_session_conversation_events_cached("session-a")
    assistant_events = [event for event in events if event.event_type == session_service.EVENT_ASSISTANT_MESSAGE]
    assert len(assistant_events) == 1
    assert "已完成资料搜集。" in str(assistant_events[0].payload.get("content") or "")
