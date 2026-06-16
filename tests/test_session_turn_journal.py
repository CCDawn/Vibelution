from __future__ import annotations

from core.chat.turn_journal import (
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_interrupted_if_open,
    append_turn_event,
    latest_open_turn_id,
    load_turn_events,
    model_visible_messages_from_events,
    turn_journal_path,
)


def test_turn_journal_appends_and_replays_interrupted_partial(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "继续修复上下文"},
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "已经读完 session_service.py", "thought": "准备写测试"},
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TURN_INTERRUPTED,
        status="interrupted",
        payload={"reason": "process_restarted", "marker": TURN_INTERRUPTED_MARKER},
    )

    events = load_turn_events(tmp_path, "session-a")
    messages = model_visible_messages_from_events(events)

    assert turn_journal_path(tmp_path, "session-a").exists()
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "继续修复上下文"
    assert messages[1]["role"] == "assistant"
    assert "已经读完" in messages[1]["content"]
    assert messages[-1]["metadata"]["kind"] == "turn_interrupted"
    assert TURN_INTERRUPTED_MARKER in messages[-1]["content"]


def test_turn_journal_synthesizes_unfinished_tool_call_result(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"name": "read_file_tool", "arguments": {"path": "agent.py"}}},
    )
    append_interrupted_if_open(tmp_path, "session-a", reason="process_restarted")

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))
    tool_message = next(item for item in messages if item.get("toolCalls"))
    tool_call = tool_message["toolCalls"][0]

    assert tool_call["name"] == "read_file_tool"
    assert tool_call["status"] == "interrupted"
    assert "返回结果前中断" in tool_call["result"]


def test_turn_journal_preserves_complete_tool_result_for_context(tmp_path):
    full_result = "terminal-line\n" * 200
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={
            "toolCall": {
                "name": "cli_tool",
                "status": "done",
                "result": full_result,
                "resultPreview": "terminal-line",
            }
        },
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))
    tool_call = messages[-1]["toolCalls"][0]

    assert tool_call["result"] == full_result
    assert tool_call["resultPreview"] == "terminal-line"


def test_append_interrupted_if_open_ignores_completed_or_active_turn(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    assert latest_open_turn_id(load_turn_events(tmp_path, "session-a")) == "turn-1"
    assert append_interrupted_if_open(tmp_path, "session-a", active_turn_id="turn-1") is None
    assert append_interrupted_if_open(tmp_path, "session-a", reason="process_restarted") is not None
    assert append_interrupted_if_open(tmp_path, "session-a", reason="process_restarted") is None
