"""Batch A: journal timestamps, tool durationMs/error, and turn header projection.

Covers the audited data break: settled turns must carry per-item timestamps
(createdAt/updatedAt), tool durations, structured tool errors (with a
lifecycle-incomplete fallback), and a turn-level work header
(turnState/turnStartedAt/turnEndedAt/turnActiveMs) on the assistant envelope.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from core.chat.turn_journal import (
    EVENT_ASSISTANT_ITEM_COMMITTED,
    EVENT_TOOL_CALL_STARTED,
    EVENT_TOOL_RESULT,
    EVENT_TURN_COMPLETED,
    EVENT_TURN_FAILED,
    EVENT_TURN_INTERRUPTED,
    EVENT_TURN_STARTED,
    EVENT_USER_MESSAGE,
    append_turn_event,
    load_turn_events,
    session_turn_items_from_events,
)
from core.runtime_manager.work_run_store import WorkRunStore
from core.ui.chat_state import save_chat_state
from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import session_service

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

_TS_START = "2026-05-18T11:55:00+00:00"
_TS_COMMIT = "2026-05-18T11:55:01+00:00"
_TS_TOOL_START = "2026-05-18T11:55:02+00:00"
_TS_TOOL_RESULT = "2026-05-18T11:55:07+00:00"
_TS_TERMINAL = "2026-05-18T11:56:30+00:00"


def _seed_tool_turn(tmp_path, *, tool_result_status: str, tool_payload: dict) -> None:
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED,
        status="running", timestamp=_TS_START,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_ASSISTANT_ITEM_COMMITTED,
        status="ready",
        payload={
            "kind": "tool_call",
            "channel": "commentary",
            "phase": "tool_call",
            "callId": "call-1",
            "toolName": "cli_tool",
            "status": "ready",
        },
        tool_call_id="call-1",
        timestamp=_TS_COMMIT,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"name": "cli_tool", "callId": "call-1"}},
        tool_call_id="call-1",
        timestamp=_TS_TOOL_START,
    )
    if tool_payload is not None:
        append_turn_event(
            tmp_path, "session-a", "turn-1", EVENT_TOOL_RESULT,
            status=tool_result_status,
            payload={"toolCall": {"name": "cli_tool", "callId": "call-1", **tool_payload}},
            tool_call_id="call-1",
            timestamp=_TS_TOOL_RESULT,
        )


def _tool_item(tmp_path) -> dict:
    items = session_turn_items_from_events(load_turn_events(tmp_path, "session-a"), turn_id="turn-1")
    return next(item for item in items if item.get("callId") == "call-1")


def test_settled_items_carry_event_timestamps_and_tool_duration(tmp_path):
    _seed_tool_turn(tmp_path, tool_result_status="done", tool_payload={"result": "ok"})
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED,
        status="completed", timestamp=_TS_TERMINAL,
    )

    items = session_turn_items_from_events(load_turn_events(tmp_path, "session-a"), turn_id="turn-1")
    tool = _tool_item(tmp_path)

    assert tool["createdAt"] == _TS_COMMIT
    assert tool["updatedAt"] == _TS_TOOL_RESULT
    assert tool["durationMs"] == 5000
    assert tool["status"] == "completed"
    assert "error" not in tool


def test_failed_timeout_tool_maps_structured_error(tmp_path):
    _seed_tool_turn(
        tmp_path,
        tool_result_status="failed",
        tool_payload={
            "status": "failed",
            "failureClass": "timeout",
            "timedOut": True,
            "error": "命令在 30 秒后超时",
        },
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_FAILED,
        status="failed_runtime", timestamp=_TS_TERMINAL,
    )

    tool = _tool_item(tmp_path)

    assert tool["status"] == "failed"
    assert tool["error"] == {"code": "fault.tool.timeout", "message": "命令在 30 秒后超时"}
    assert tool["durationMs"] == 5000


def test_tool_without_terminal_event_closes_as_lifecycle_incomplete(tmp_path):
    # Tool committed ready, never executed, then the turn settled anyway
    # (executor early-exit).  The settled transcript must not freeze a running row.
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED,
        status="running", timestamp=_TS_START,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_ASSISTANT_ITEM_COMMITTED,
        status="ready",
        payload={
            "kind": "tool_call",
            "channel": "commentary",
            "phase": "tool_call",
            "callId": "call-1",
            "toolName": "cli_tool",
            "status": "ready",
        },
        tool_call_id="call-1",
        timestamp=_TS_COMMIT,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED,
        status="completed", timestamp=_TS_TERMINAL,
    )

    tool = _tool_item(tmp_path)

    assert tool["status"] == "failed"
    assert tool["error"] == {
        "code": "fault.runtime.toolLifecycleIncomplete",
        "message": "Tool call ended without a terminal event.",
    }
    assert tool["updatedAt"] == _TS_TERMINAL
    assert "durationMs" not in tool


def test_settled_assistant_message_items_carry_commit_timestamp(tmp_path):
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_STARTED,
        status="running", timestamp=_TS_START,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        payload={
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "status": "completed",
            "itemId": "answer-1",
            "text": "最终答案",
        },
        timestamp=_TS_TOOL_RESULT,
    )
    append_turn_event(
        tmp_path, "session-a", "turn-1", EVENT_TURN_COMPLETED,
        status="completed", timestamp=_TS_TERMINAL,
    )

    items = session_turn_items_from_events(load_turn_events(tmp_path, "session-a"), turn_id="turn-1")
    message = next(item for item in items if item.get("type") == "assistant_message")

    assert message["createdAt"] == _TS_TOOL_RESULT
    assert message["updatedAt"] == _TS_TOOL_RESULT


def _append_header_turn(tmp_path, turn_id: str, *, terminal_type: str, terminal_status: str) -> None:
    append_turn_event(
        tmp_path, "session-h", turn_id, EVENT_TURN_STARTED,
        status="running", timestamp=_TS_START,
    )
    append_turn_event(
        tmp_path, "session-h", turn_id, terminal_type,
        status=terminal_status, timestamp=_TS_TERMINAL,
    )


def test_assistant_turn_header_settled_completed(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _append_header_turn(tmp_path, "turn-ok", terminal_type=EVENT_TURN_COMPLETED, terminal_status="completed")

    header = session_service._assistant_turn_header_fields(
        "session-h", "turn-ok", streaming=False, fallback_status="completed",
    )

    assert header == {
        "turnState": "completed",
        "turnStartedAt": _TS_START,
        "turnEndedAt": _TS_TERMINAL,
        "turnActiveMs": 90_000,
    }


def test_assistant_turn_header_maps_interrupted_and_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    _append_header_turn(
        tmp_path, "turn-stopped", terminal_type=EVENT_TURN_INTERRUPTED, terminal_status="stopped_by_user",
    )
    _append_header_turn(
        tmp_path, "turn-provider", terminal_type=EVENT_TURN_FAILED, terminal_status="failed_provider",
    )

    stopped = session_service._assistant_turn_header_fields("session-h", "turn-stopped")
    provider = session_service._assistant_turn_header_fields("session-h", "turn-provider")

    assert stopped["turnState"] == "interrupted"
    assert provider["turnState"] == "failed"
    assert stopped["turnActiveMs"] == provider["turnActiveMs"] == 90_000


def test_assistant_turn_header_live_running(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_turn_event(
        tmp_path, "session-h", "turn-live", EVENT_TURN_STARTED,
        status="running", timestamp=_TS_START,
    )

    header = session_service._assistant_turn_header_fields(
        "session-h", "turn-live", streaming=True, fallback_status="running",
    )

    assert header == {"turnState": "running", "turnStartedAt": _TS_START}
    assert "turnEndedAt" not in header
    assert "turnActiveMs" not in header


def test_assistant_turn_header_falls_back_to_work_run(monkeypatch, tmp_path):
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    store = WorkRunStore(root=tmp_path / "work-runs")
    monkeypatch.setattr(session_service, "_WORK_RUN_STORE", store)
    store.persist_snapshot(
        "chat_turn",
        {
            "runId": "turn-wr",
            "runKind": "chat_turn",
            "sessionId": "session-h",
            "status": "completed",
            "startedAt": _TS_START,
            "finishedAt": _TS_TERMINAL,
        },
        active_run_id="",
    )

    header = session_service._assistant_turn_header_fields(
        "session-h", "turn-wr", streaming=False, fallback_status="completed",
    )

    assert header["turnState"] == "completed"
    assert header["turnStartedAt"] == _TS_START
    assert header["turnEndedAt"] == _TS_TERMINAL
    assert header["turnActiveMs"] == 90_000


def test_session_detail_envelope_carries_turn_header_and_item_timestamps(monkeypatch, tmp_path):
    save_chat_state(
        tmp_path,
        {
            "version": 1,
            "active_conversation_id": "session-live",
            "conversations": [
                {
                    "conversation_id": "session-live",
                    "title": "时间戳投影",
                    "agent_id": "agent-a",
                    "agentId": "agent-a",
                    "updated_at": _TS_TERMINAL,
                    "last_turn_status": "ready",
                    "last_turn_terminal_turn_id": "turn-wire",
                    "messages": [
                        {
                            "role": "user",
                            "content": "跑个工具",
                            "timestamp": _TS_START,
                            "metadata": {"turnId": "turn-wire"},
                        }
                    ],
                }
            ],
        },
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    append_turn_event(tmp_path, "session-live", "turn-wire", EVENT_TURN_STARTED, status="running", timestamp=_TS_START)
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "跑个工具"},
        timestamp=_TS_START,
    )
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_ASSISTANT_ITEM_COMMITTED,
        status="ready",
        payload={
            "kind": "tool_call",
            "channel": "commentary",
            "phase": "tool_call",
            "callId": "call-1",
            "toolName": "cli_tool",
            "status": "ready",
        },
        tool_call_id="call-1",
        timestamp=_TS_COMMIT,
    )
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_TOOL_CALL_STARTED,
        status="running",
        payload={"toolCall": {"name": "cli_tool", "callId": "call-1"}},
        tool_call_id="call-1",
        timestamp=_TS_TOOL_START,
    )
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_TOOL_RESULT,
        status="done",
        payload={"toolCall": {"name": "cli_tool", "callId": "call-1", "result": "ok"}},
        tool_call_id="call-1",
        timestamp=_TS_TOOL_RESULT,
    )
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_ASSISTANT_ITEM_COMMITTED,
        status="completed",
        payload={
            "kind": "assistant_message",
            "channel": "answer",
            "phase": "final_answer",
            "status": "completed",
            "itemId": "answer-1",
            "text": "工具跑完了",
        },
        timestamp=_TS_TOOL_RESULT,
    )
    append_turn_event(
        tmp_path, "session-live", "turn-wire", EVENT_TURN_COMPLETED,
        status="completed", timestamp=_TS_TERMINAL,
    )

    response = client.get("/api/sessions/session-live")

    assert response.status_code == 200
    payload = response.json()
    assistant = next(m for m in payload["messages"] if m.get("role") == "assistant")
    assert assistant["turnState"] == "completed"
    assert assistant["turnStartedAt"] == _TS_START
    assert assistant["turnEndedAt"] == _TS_TERMINAL
    assert assistant["turnActiveMs"] == 90_000

    tool_item = next(item for item in assistant["turnItems"] if item.get("type") == "tool_call")
    assert tool_item["createdAt"] == _TS_COMMIT
    assert tool_item["updatedAt"] == _TS_TOOL_RESULT
    assert tool_item["durationMs"] == 5000

    answer_item = next(item for item in assistant["turnItems"] if item.get("type") == "agent_message")
    assert answer_item["createdAt"] == _TS_TOOL_RESULT
    assert answer_item["updatedAt"] == _TS_TOOL_RESULT
