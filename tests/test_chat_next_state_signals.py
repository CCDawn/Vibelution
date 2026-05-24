# -*- coding: utf-8 -*-
"""next-state signal 回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

from core.evaluation.chat_next_state_signals import (
    append_chat_next_state_signal,
    list_chat_next_state_signals,
    resolve_chat_next_state_signal_path,
    summarize_chat_next_state_signals,
)


def test_append_chat_next_state_signal_round_trip(tmp_path: Path, monkeypatch):
    recorded_events: list[dict] = []

    def fake_record_runtime_scene_event(component, phase, event_code, **kwargs):
        recorded_events.append(
            {
                "component": component,
                "phase": phase,
                "eventCode": event_code,
                **kwargs,
            }
        )
        return {"accepted": True}

    monkeypatch.setattr(
        "core.web.services.runtime_scene_service.record_runtime_scene_event",
        fake_record_runtime_scene_event,
    )

    signal = append_chat_next_state_signal(
        project_root=tmp_path,
        session_id="session-live",
        turn_id="turn-1",
        source="USER",
        kind="user-stops",
        polarity="NEGATIVE",
        mode="DIRECTIVE",
        related_event_code="conversation.user_stop_requested",
        summary="用户请求停止当前对话轮次。 " + "x" * 400,
        metadata={
            "toolName": "read_file_tool",
            "note": "x" * 500,
            "nested": {"reason": "provider_failure"},
        },
    )

    signal_path = resolve_chat_next_state_signal_path(tmp_path)
    assert signal_path == tmp_path / "workspace" / "evaluation" / "chat_next_state_signals.jsonl"
    assert signal_path.exists()

    payloads = [json.loads(line) for line in signal_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(payloads) == 1
    assert payloads[0]["signalId"] == signal["signalId"]
    assert payloads[0]["source"] == "user"
    assert payloads[0]["kind"] == "user_stops"
    assert payloads[0]["polarity"] == "negative"
    assert payloads[0]["mode"] == "directive"
    assert payloads[0]["turnId"] == "turn-1"
    assert payloads[0]["metadata"]["toolName"] == "read_file_tool"
    assert len(payloads[0]["summary"]) <= 240

    listed = list_chat_next_state_signals(project_root=tmp_path, session_id="session-live", turn_id="turn-1")
    assert listed == payloads
    summary = summarize_chat_next_state_signals(listed, limit=1)
    assert summary[0]["signalId"] == signal["signalId"]
    assert summary[0]["kind"] == "user_stops"
    assert summary[0]["turnId"] == "turn-1"

    assert recorded_events
    assert recorded_events[0]["component"] == "conversation"
    assert recorded_events[0]["eventCode"] == "conversation.next_state_signal.recorded"
    assert recorded_events[0]["child_log_path"] == "conversations/chat-next-state-signals.jsonl"
    assert recorded_events[0]["child_log_payload"]["signalId"] == signal["signalId"]
