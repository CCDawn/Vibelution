from pathlib import Path

from core.ui.chat_state import CHAT_STATE_VERSION, save_chat_state
from core.web.services import session_service
from core.web.services import supervised_conversation_harness_adapter as adapter


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
                    "messages": [
                        {
                            "role": "user",
                            "content": "执行监督进化 fixture",
                            "metadata": {"turnId": "turn-1"},
                        },
                        {
                            "role": "assistant",
                            "content": assistant_text,
                            "metadata": {"turnId": "turn-1"},
                        },
                    ],
                }
            ],
        },
    )
    with session_service._RUNNING_SESSIONS_LOCK:
        session_service._RUNNING_SESSION_IDS.add("session-hidden")
        session_service._SESSION_ACTIVE_TURN_IDS["session-hidden"] = "turn-next"

    snapshot = session_service.get_session_turn_completion_snapshot("session-hidden", "turn-1")

    assert snapshot["terminal"] is True
    assert snapshot["terminalStatus"] == "ready"
    assert snapshot["completionSource"] == "assistant_marker"
    assert snapshot["completionRecovered"] is True
    assert snapshot["assistantText"] == assistant_text
    assert snapshot["assistantTurnId"] == "turn-1"
    assert snapshot["lastTurnStatus"] == "running"
    assert snapshot["activeTurnId"] == "turn-next"
