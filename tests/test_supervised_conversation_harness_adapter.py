from pathlib import Path

from core.chat.conversation_ledger import (
    EVENT_ASSISTANT_MESSAGE,
    EVENT_USER_MESSAGE,
    append_conversation_event,
)
from core.chat.turn_journal import EVENT_TOOL_RESULT, append_turn_event
from core.ui.chat_state import CHAT_STATE_VERSION, save_chat_state
from core.web.services import session_service
from core.web.services import supervised_conversation_harness_adapter as adapter


def test_conversation_harness_summary_uses_turn_journal_when_final_message_loses_tool_calls(tmp_path: Path):
    session_id = "session-hidden-supervised"
    turn_id = "turn-1"
    append_turn_event(
        tmp_path,
        session_id,
        turn_id,
        EVENT_TOOL_RESULT,
        status="done",
        payload={
            "toolCall": {
                "name": "open_evolution_transaction_tool",
                "status": "done",
                "arguments": {"summary": "supervised probe"},
                "result": '{"status":"success","txn_id":"txn-journal"}',
            }
        },
        source="session_ui_capture",
    )

    detail = {
        "id": session_id,
        "messages": [
            {"role": "user", "content": "run supervised probe"},
            {
                "role": "assistant",
                "content": "27 passed, closing transaction",
                "tool_calls": [
                    {
                        "name": "close_evolution_transaction_tool",
                        "status": "done",
                        "arguments": {"txn_id": "txn-journal", "status": "success"},
                        "result": '{"status":"success","txn_id":"txn-journal","transaction_status":"success"}',
                    }
                ],
            },
        ],
    }

    summary = adapter._conversation_harness_evolution_summary(
        detail,
        assistant_text="27 passed, closing transaction",
        restart_expected=False,
        repo_root=tmp_path,
    )

    assert summary["transaction"] == {
        "opened": True,
        "closed": True,
        "status": "success",
        "txn_id": "txn-journal",
    }
    assert "open_evolution_transaction_tool:success" in summary["tool_sequence_tail"]
    assert "close_evolution_transaction_tool:success" in summary["tool_sequence_tail"]


def test_conversation_harness_recovers_completed_turn_from_completion_snapshot(monkeypatch, tmp_path: Path):
    assistant_text = (
        "完成动态重规划。\n"
        'SUPERVISED_FINAL_STATE: {"calendar_event":"rescheduled","new_time":"10:30",'
        '"verified_after_change":true,"replanned":true}'
    )
    stopped: list[str] = []

    monkeypatch.setattr(
        adapter,
        "create_supervised_agent_session",
        lambda **kwargs: {"id": "session-hidden"},
    )
    monkeypatch.setattr(
        adapter,
        "submit_session_message",
        lambda *args, **kwargs: {"turnId": "turn-1"},
    )
    monkeypatch.setattr(
        adapter,
        "get_session_detail",
        lambda session_id: {
            "id": session_id,
            "lastTurnStatus": "running",
            "updatedAt": "2026-06-16T01:32:59",
            "messages": [
                {
                    "role": "user",
                    "content": "执行监督进化 dynamic_replanning fixture 候选探针",
                    "metadata": {"turnId": "turn-1"},
                },
                {
                    "role": "assistant",
                    "content": assistant_text,
                    "metadata": {"turnId": "turn-1"},
                },
            ],
        },
    )
    monkeypatch.setattr(adapter, "request_stop_session_turn", lambda session_id: stopped.append(session_id))
    monkeypatch.setattr(
        adapter,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id: {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": True,
            "terminalStatus": "ready",
            "completionSource": "assistant_marker",
            "completionRecovered": True,
            "assistantText": assistant_text,
            "lastTurnStatus": "running",
            "messageCount": 2,
        },
        raising=False,
    )
    ticks = iter([0.0, 0.1, 0.2, 0.3])
    monkeypatch.setattr(adapter.time, "monotonic", lambda: next(ticks, 2.0))
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: None)

    result = adapter.run_supervised_conversation_harness(
        repo_root=tmp_path,
        mode="single_turn",
        prompt="probe",
        timeout_seconds=1,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=False,
        scenario="dynamic_replanning_fixture",
        agent_binding={"agentId": "agent-candidate", "role": "candidate"},
    )

    assert result.status == "success"
    assert result.returncode == 0
    assert result.evolution_summary["final_state"] == {
        "calendar_event": "rescheduled",
        "new_time": "10:30",
        "verified_after_change": True,
        "replanned": True,
    }
    assert result.evolution_summary["conversation_backend"]["completion_source"] == "assistant_marker"
    assert result.evolution_summary["conversation_backend"]["completion_recovered"] is True
    assert stopped == []


def test_conversation_harness_passes_workspace_override_to_supervised_session(monkeypatch, tmp_path: Path):
    candidate_path = tmp_path / "candidate-worktree"
    candidate_path.mkdir()
    captured_session: dict[str, object] = {}
    captured_submit: dict[str, object] = {}

    monkeypatch.setattr(
        adapter,
        "create_supervised_agent_session",
        lambda **kwargs: captured_session.update(kwargs) or {"id": "session-hidden"},
    )
    monkeypatch.setattr(
        adapter,
        "submit_session_message",
        lambda *args, **kwargs: captured_submit.update({"args": args, **kwargs}) or {"turnId": "turn-1"},
    )
    monkeypatch.setattr(
        adapter,
        "get_session_detail",
        lambda session_id: {
            "id": session_id,
            "lastTurnStatus": "ready",
            "updatedAt": "2026-06-16T01:32:59",
            "messages": [
                {"role": "user", "content": "improve candidate"},
                {"role": "assistant", "content": "done"},
            ],
        },
    )
    monkeypatch.setattr(
        adapter,
        "get_session_turn_completion_snapshot",
        lambda session_id, turn_id: {
            "sessionId": session_id,
            "turnId": turn_id,
            "terminal": True,
            "terminalStatus": "ready",
            "assistantText": "done",
        },
        raising=False,
    )
    monkeypatch.setattr(adapter.time, "sleep", lambda seconds: None)

    result = adapter.run_supervised_conversation_harness(
        repo_root=candidate_path,
        mode="single_turn",
        prompt="improve candidate",
        timeout_seconds=1,
        expect_restart=False,
        post_restart_observe_seconds=0,
        keep_worktree=True,
        scenario="candidate_self_improvement",
        agent_binding={"agentId": "agent-candidate", "role": "candidate"},
        workspace_override=candidate_path,
    )

    assert result.status == "success"
    assert captured_session["metadata"]["workspaceOverride"] == str(candidate_path)
    assert captured_submit["message_metadata"]["workspaceOverride"] == str(candidate_path)
    assert captured_submit["message_source"] == "supervised_evolution"


def test_session_turn_completion_snapshot_recovers_finished_hidden_turn(tmp_path: Path, monkeypatch):
    assistant_text = (
        "完成候选探针。\n"
        'SUPERVISED_FINAL_STATE: {"case_id":"dynamic_replanning","status":"ok"}'
    )
    monkeypatch.setattr(session_service, "PROJECT_ROOT", tmp_path)
    save_chat_state(
        tmp_path,
        {
            "version": CHAT_STATE_VERSION,
            "active_conversation_id": "session-hidden",
            "conversations": [
                {
                    "conversation_id": "session-hidden",
                    "title": "supervised hidden",
                    "last_turn_status": "running",
                }
            ],
        },
    )
    append_conversation_event(
        tmp_path,
        "session-hidden",
        "turn-1",
        EVENT_USER_MESSAGE,
        status="recorded",
        payload={"content": "执行监督进化 fixture", "metadata": {"turnId": "turn-1"}},
    )
    append_conversation_event(
        tmp_path,
        "session-hidden",
        "turn-1",
        EVENT_ASSISTANT_MESSAGE,
        status="completed",
        payload={"content": assistant_text, "metadata": {"turnId": "turn-1"}},
    )
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.add("session-hidden")
        session_service._SESSION_ACTIVE_TURN_IDS["session-hidden"] = "turn-next"
    try:
        snapshot = session_service.get_session_turn_completion_snapshot("session-hidden", "turn-1")

        assert snapshot["terminal"] is True
        assert snapshot["terminalStatus"] == "ready"
        assert snapshot["completionSource"] == "assistant_marker"
        assert snapshot["completionRecovered"] is True
        assert snapshot["assistantText"] == assistant_text
        assert snapshot["assistantTurnId"] == "turn-1"
        assert snapshot["lastTurnStatus"] == "running"
        assert snapshot["activeTurnId"] == "turn-next"
    finally:
        with session_service._RUNNING_SESSIONS_LOCK:
            session_service._RUNNING_SESSION_IDS.discard("session-hidden")
            session_service._SESSION_ACTIVE_TURN_IDS.pop("session-hidden", None)
