from __future__ import annotations

from core.chat.conversation_ledger import (
    EVENT_USER_MESSAGE,
    append_conversation_event,
    conversation_visible_messages_from_events,
    latest_ledger_sequence,
    load_conversation_events,
)
from core.ui.chat_state import load_chat_state, save_chat_state, save_session_chat_state


SESSION_ID = "session-legacy"


def _conversation(*, status: str, messages: object, preserved: bool = False) -> dict:
    payload = {
        "conversation_id": SESSION_ID,
        "conversationId": SESSION_ID,
        "title": "legacy",
        "last_turn_status": status,
        "messages": messages,
    }
    if preserved:
        payload["legacy_messages_preserved"] = True
    return payload


def _state(conversation: dict) -> dict:
    return {"active_conversation_id": SESSION_ID, "conversations": [conversation]}


def _visible_texts(tmp_path) -> list[str]:
    return [
        str(item.get("content") or "")
        for item in conversation_visible_messages_from_events(
            load_conversation_events(tmp_path, SESSION_ID)
        )
    ]


def test_queued_running_stopping_blobs_materialize_then_drop(tmp_path):
    for status in ("queued", "running", "stopping"):
        session_id = f"session-{status}"
        conversation = {
            "conversation_id": session_id,
            "last_turn_status": status,
            "messages": [
                {"role": "user", "content": f"{status}-user", "timestamp": "2026-08-17T00:00:00Z"},
                {"role": "assistant", "content": f"{status}-assistant", "timestamp": "2026-08-17T00:00:01Z"},
            ],
        }
        save_session_chat_state(tmp_path, session_id, conversation)
        loaded = load_chat_state(tmp_path)
        row = next(item for item in loaded["conversations"] if item.get("conversation_id") == session_id)
        assert "messages" not in row
        assert latest_ledger_sequence(tmp_path, session_id) > 0
        texts = [
            str(item.get("content") or "")
            for item in conversation_visible_messages_from_events(
                load_conversation_events(tmp_path, session_id)
            )
        ]
        assert f"{status}-user" in texts
        assert f"{status}-assistant" in texts


def test_preserved_flag_with_empty_ledger_materializes_once(tmp_path):
    save_chat_state(
        tmp_path,
        _state(
            _conversation(
                status="ready",
                preserved=True,
                messages=[
                    {"role": "user", "content": "preserved-user", "timestamp": "2026-08-17T00:00:00Z"},
                ],
            )
        ),
    )
    loaded = load_chat_state(tmp_path)["conversations"][0]
    assert "messages" not in loaded
    assert "legacy_messages_preserved" not in loaded
    assert latest_ledger_sequence(tmp_path, SESSION_ID) > 0
    first_seq = latest_ledger_sequence(tmp_path, SESSION_ID)

    save_chat_state(
        tmp_path,
        _state(
            _conversation(
                status="ready",
                preserved=True,
                messages=[
                    {"role": "user", "content": "second-pass-should-not-clobber", "timestamp": "2026-08-17T00:00:02Z"},
                ],
            )
        ),
    )
    assert latest_ledger_sequence(tmp_path, SESSION_ID) == first_seq
    assert "second-pass-should-not-clobber" not in _visible_texts(tmp_path)
    assert "preserved-user" in _visible_texts(tmp_path)
    assert "messages" not in load_chat_state(tmp_path)["conversations"][0]


def test_existing_canonical_ledger_is_not_clobbered(tmp_path):
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-canonical",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "canonical-user"},
        timestamp="2026-08-17T00:00:00Z",
    )
    save_chat_state(
        tmp_path,
        _state(
            _conversation(
                status="running",
                messages=[
                    {"role": "user", "content": "blob-should-not-win", "timestamp": "2026-08-17T00:00:03Z"},
                ],
            )
        ),
    )
    assert "canonical-user" in _visible_texts(tmp_path)
    assert "blob-should-not-win" not in _visible_texts(tmp_path)
    assert "messages" not in load_chat_state(tmp_path)["conversations"][0]


def test_corrupt_blob_does_not_clobber_existing_ledger(tmp_path):
    append_conversation_event(
        tmp_path,
        SESSION_ID,
        "turn-canonical",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "already-canonical"},
        timestamp="2026-08-17T00:00:00Z",
    )
    save_chat_state(
        tmp_path,
        _state(_conversation(status="running", messages="not-a-list")),
    )
    assert "already-canonical" in _visible_texts(tmp_path)
    loaded = load_chat_state(tmp_path)["conversations"][0]
    assert "messages" not in loaded


def test_interrupted_materialize_resumes_without_duplicating(tmp_path):
    conversation = _conversation(
        status="queued",
        messages=[
            {"role": "user", "content": "only-once", "timestamp": "2026-08-17T00:00:00Z"},
        ],
    )
    save_session_chat_state(tmp_path, SESSION_ID, conversation)
    first_seq = latest_ledger_sequence(tmp_path, SESSION_ID)
    conversation["messages"] = [
        {"role": "user", "content": "only-once", "timestamp": "2026-08-17T00:00:00Z"},
    ]
    save_session_chat_state(tmp_path, SESSION_ID, conversation)
    assert latest_ledger_sequence(tmp_path, SESSION_ID) == first_seq
    assert _visible_texts(tmp_path).count("only-once") == 1
