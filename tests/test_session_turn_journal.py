from __future__ import annotations

from core.chat.turn_journal import (
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_COMPACTION_CHECKPOINT,
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


def test_turn_journal_skips_paired_tool_start_when_result_exists(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"id": "tool-1", "name": "cli_tool", "arguments": {"cmd": "pytest"}}},
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"id": "tool-1", "name": "cli_tool", "status": "done", "result": "All checks passed"}},
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))
    tool_calls = [message["toolCalls"][0] for message in messages if message.get("toolCalls")]

    assert len(tool_calls) == 1
    assert tool_calls[0]["status"] == "done"
    assert tool_calls[0]["result"] == "All checks passed"


def test_turn_journal_visibility_flag_excludes_internal_event(tmp_path):
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_ASSISTANT_PARTIAL,
        status="running",
        payload={"content": "内部快照"},
        visible_in_model=False,
        projection_kind="ui_stream",
    )

    events = load_turn_events(tmp_path, "session-a")
    assert events[0].schema_version == 2
    assert events[0].visible_in_model is False
    assert events[0].projection_kind == "ui_stream"
    assert model_visible_messages_from_events(events) == []


def test_turn_journal_replays_compaction_checkpoint_and_cli_result(tmp_path):
    append_turn_event(
        tmp_path,
        "session-a",
        "checkpoint",
        EVENT_COMPACTION_CHECKPOINT,
        status="ready",
        payload={"summary": "用户要求继续修复 CLI 会话幂等。"},
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-cli",
        EVENT_CLI_TASK_RESULT,
        status="timeout",
        payload={
            "taskId": "cli-task-1",
            "status": "timeout",
            "adapterId": "mimo_code",
            "terminalSessionId": "cli-term-1",
            "resultSegments": [{"kind": "error", "text": "卡在测试等待"}],
            "stdoutPreview": "卡在测试等待",
        },
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))

    assert messages[0]["metadata"]["kind"] == EVENT_COMPACTION_CHECKPOINT
    assert "继续修复 CLI" in messages[0]["content"]
    tool_call = messages[1]["toolCalls"][0]
    assert tool_call["name"] == "cli_agent_run_tool"
    assert tool_call["status"] == "timeout"
    assert tool_call["resultSegments"] == [{"kind": "error", "text": "卡在测试等待"}]


def test_turn_journal_replays_cli_lifecycle_closed_message(tmp_path):
    append_turn_event(
        tmp_path,
        "session-a",
        "",
        EVENT_CLI_SESSION_LIFECYCLE,
        status="closed",
        payload={
            "event": "closed",
            "label": "MiMo Code",
            "adapterId": "mimo_code",
            "terminalSessionId": "cli-term-1",
            "cwd": str(tmp_path),
            "mode": "readonly",
        },
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))

    assert messages == [
        {
            "role": "assistant",
            "content": "MiMo Code 已关闭。",
            "metadata": {
                "kind": EVENT_CLI_SESSION_LIFECYCLE,
                "turnId": "",
                "eventId": messages[0]["metadata"]["eventId"],
                "event": "closed",
                "terminalSessionId": "cli-term-1",
                "cliRunId": "",
                "adapterId": "mimo_code",
                "cwd": str(tmp_path),
                "mode": "readonly",
            },
        }
    ]


def test_append_interrupted_if_open_ignores_completed_or_active_turn(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    assert latest_open_turn_id(load_turn_events(tmp_path, "session-a")) == "turn-1"
    assert append_interrupted_if_open(tmp_path, "session-a", active_turn_id="turn-1") is None
    assert append_interrupted_if_open(tmp_path, "session-a", reason="process_restarted") is not None
    assert append_interrupted_if_open(tmp_path, "session-a", reason="process_restarted") is None
