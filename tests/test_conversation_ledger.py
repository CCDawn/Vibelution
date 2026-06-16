from __future__ import annotations

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_RESULT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_conversation_event,
    conversation_ledger_path,
    conversation_model_messages_from_events,
    latest_ledger_sequence,
    load_conversation_events,
    project_conversation_ledger,
)


def test_conversation_ledger_appends_and_projects_model_messages(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续修复单一事实源"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-1", "name": "cli_tool", "status": "done", "result": "测试通过"}},
        tool_call_id="tool-1",
    )

    events = load_conversation_events(tmp_path, "session-a")
    projection = project_conversation_ledger(events)
    messages = conversation_model_messages_from_events(events)

    assert conversation_ledger_path(tmp_path, "session-a").exists()
    assert [event.sequence for event in events] == [1, 2, 3]
    assert projection.latest_seq == 3
    assert projection.to_metadata()["ledgerSeq"] == 3
    assert latest_ledger_sequence(tmp_path, "session-a") == 3
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "继续修复单一事实源"
    assert messages[1]["role"] == "assistant"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "tool-1"
    assert "测试通过" in messages[2]["content"]


def test_conversation_ledger_preserves_interrupted_partial(tmp_path):
    append_conversation_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经完成前半部分。"},
    )
    append_conversation_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "process_restarted", "marker": TURN_INTERRUPTED_MARKER},
    )

    messages = conversation_model_messages_from_events(load_conversation_events(tmp_path, "session-a"))
    contents = [str(message.get("content") or "") for message in messages]

    assert "已经完成前半部分。" in contents
    assert any(TURN_INTERRUPTED_MARKER in content for content in contents)
