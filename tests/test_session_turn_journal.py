from __future__ import annotations

import pytest

from core.chat.turn_journal import (
    EVENT_ASSISTANT_DELTA_COMMITTED,
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_ASSISTANT_MESSAGE,
    EVENT_CLI_SESSION_LIFECYCLE,
    EVENT_CLI_TASK_RESULT,
    EVENT_COMPACTION_CHECKPOINT,
    EVENT_ASSISTANT_PARTIAL,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    TURN_INTERRUPTED_MARKER,
    append_interrupted_if_open,
    append_canonical_turn_outcome,
    append_turn_event,
    latest_open_turn_id,
    load_turn_events,
    model_visible_messages_from_events,
    session_turn_items_from_events,
    turn_journal_path,
)
from core.llm.types import CanonicalItemIdentity, CanonicalToolCall, LLMProtocolEvent, TurnOutcome


def test_canonical_outcomes_commit_items_before_tools_and_project_safe_v2(tmp_path):
    identity = CanonicalItemIdentity("session-a", "turn-1", "inv-1", 0, "msg-1")
    commentary = LLMProtocolEvent(
        kind="item_completed",
        sequence=2,
        session_id="session-a",
        turn_id="turn-1",
        invocation_id="inv-1",
        iteration=0,
        item_id="comment-1",
        channel="commentary",
        phase="commentary",
        status="completed",
        text="我先检查。",
        diagnostic_summary={"protocol": "responses", "provider": "relay"},
    )
    tool_event = LLMProtocolEvent(
        kind="item_completed",
        sequence=3,
        session_id="session-a",
        turn_id="turn-1",
        invocation_id="inv-1",
        iteration=0,
        item_id="call-item-1",
        call_id="call-1",
        tool_name="read_file",
        channel="commentary",
        phase="tool_call",
        status="ready",
    )
    tool_identity = CanonicalItemIdentity("session-a", "turn-1", "inv-1", 0, "call-item-1")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_canonical_turn_outcome(
        tmp_path,
        "session-a",
        "turn-1",
        TurnOutcome(
            kind="tool_calls",
            identity=identity,
            events=(commentary, tool_event),
            tool_calls=(CanonicalToolCall(tool_identity, "call-1", "read_file", {"path": "a.txt"}),),
            pending_tool_call_ids=("call-1",),
            terminal_event_seen=True,
        ),
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"name": "read_file", "callId": "call-1"}},
    )
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"name": "read_file", "callId": "call-1", "result": "ok"}},
    )
    final_identity = CanonicalItemIdentity("session-a", "turn-1", "inv-2", 1, "answer-1")
    append_canonical_turn_outcome(
        tmp_path,
        "session-a",
        "turn-1",
        TurnOutcome.final_answer(identity=final_identity, text="最终答案"),
    )
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")

    events = load_turn_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [
        EVENT_TURN_STARTED,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TOOL_CALL_STARTED,
        EVENT_TOOL_RESULT,
        EVENT_ASSISTANT_ITEM_COMMITTED,
        EVENT_TURN_COMPLETED,
    ]
    assert EVENT_ASSISTANT_DELTA_COMMITTED not in [event.event_type for event in events]
    assert [
        message["content"]
        for message in model_visible_messages_from_events(events)
        if message["role"] == "assistant" and str(message.get("content") or "").strip()
    ] == ["最终答案"]

    items = session_turn_items_from_events(events, turn_id="turn-1")
    assert items[-1] == {
        "version": 2,
        "id": "answer-1:0",
        "type": "assistant_message",
        "sessionId": "session-a",
        "turnId": "turn-1",
        "invocationId": "inv-2",
        "iteration": 1,
        "itemId": "answer-1",
        "revision": 0,
        "sequence": events[-2].sequence,
        "kind": "assistant_message",
        "channel": "answer",
        "phase": "final_answer",
        "status": "completed",
        "protocol": "canonical",
        "provisional": False,
        "terminal": True,
        "text": "最终答案",
    }
    assert "replay" not in str(items).lower()
    assert "opaque" not in str(items).lower()


def test_turn_journal_rejects_model_visible_events_after_terminal_turn(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED, status="completed")

    with pytest.raises(ValueError, match="terminal event"):
        append_turn_event(
            tmp_path,
            "session-a",
            "turn-1",
            EVENT_TOOL_RESULT,
            status="done",
            payload={"toolCall": {"name": "read_file_tool", "status": "done", "result": "late"}},
        )

    with pytest.raises(ValueError, match="terminal event"):
        append_turn_event(
            tmp_path,
            "session-a",
            "turn-1",
            EVENT_ASSISTANT_MESSAGE,
            status="completed",
            payload={"content": "late answer"},
        )

    events = load_turn_events(tmp_path, "session-a")
    assert [event.event_type for event in events] == [EVENT_TURN_STARTED, EVENT_TURN_COMPLETED]


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


def test_turn_journal_replays_user_message_with_references_only(tmp_path):
    references = [
        {
            "referenceId": "session:beta",
            "kind": "session",
            "sessionId": "beta",
            "title": "Beta Agent",
        }
    ]
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "", "references": references},
        timestamp="2026-06-24T00:00:00Z",
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))

    assert messages == [
        {
            "role": "user",
            "content": "",
            "timestamp": "2026-06-24T00:00:00Z",
            "attachments": [],
            "references": references,
            "metadata": {
                "kind": "journal_user_message",
                "turnId": "turn-1",
                "eventId": messages[0]["metadata"]["eventId"],
            },
        }
    ]


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


def test_turn_journal_replays_returned_degraded_tool_result_as_terminal(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="running",
        payload={
            "toolCall": {
                "name": "cli_tool",
                "status": "running",
                "summary": "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
                "result": "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
                "transportStatus": "returned",
                "semanticStatus": "degraded",
                "timedOut": False,
            }
        },
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))
    tool_call = messages[-1]["toolCalls"][0]

    assert tool_call["status"] == "done"
    assert tool_call["semanticStatus"] == "degraded"
    assert "[跨平台警告]" in tool_call["summary"]


def test_turn_journal_replays_returned_timed_out_tool_result_as_timeout(tmp_path):
    append_turn_event(tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED, status="running")
    append_turn_event(
        tmp_path,
        "session-a",
        "turn-1",
        EVENT_TOOL_RESULT,
        status="running",
        payload={
            "toolCall": {
                "name": "cli_tool",
                "status": "running",
                "summary": "[超时] cli_tool 执行超时",
                "result": "[超时] cli_tool 执行超时",
                "transportStatus": "returned",
                "timedOut": True,
            }
        },
    )

    messages = model_visible_messages_from_events(load_turn_events(tmp_path, "session-a"))
    tool_call = messages[-1]["toolCalls"][0]

    assert tool_call["status"] == "timeout"
    assert tool_call["timedOut"] is True


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


def test_turn_journal_replays_context_compression_marker_and_cli_result(tmp_path):
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

    assert messages[0]["metadata"]["kind"] == "context_compression_marker"
    assert messages[0]["metadata"]["title"] == "上下文已压缩"
    assert "继续修复 CLI" in messages[0]["metadata"]["summaryPreview"]
    assert messages[0]["content"] == ""
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
            "timestamp": messages[0]["timestamp"],
            "metadata": {
                "kind": EVENT_CLI_SESSION_LIFECYCLE,
                "turnId": "",
                "eventId": messages[0]["metadata"]["eventId"],
                "event": "closed",
                "lifecycleKey": "",
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
