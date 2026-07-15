import json

from tools import conversation_log_tools


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_runtime_scene_inspection_returns_one_compact_agent_trace_for_a_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    scene = tmp_path / "logs" / "runtime_scenes" / "scene-trace"
    (scene / "manifest.json").parent.mkdir(parents=True)
    (scene / "manifest.json").write_text(json.dumps({"runtime_scene_id": "scene-trace"}), encoding="utf-8")

    identity = {"sessionId": "session-1", "turnId": "turn-1", "invocationId": "invoke-1"}
    _write_jsonl(
        scene / "events" / "conversation.jsonl",
        [
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2026-07-15T01:00:00Z",
                "fields": identity,
            },
            {
                "event_code": "conversation.turn.tool_call",
                "outcome": "succeeded",
                "ts": "2026-07-15T01:00:03Z",
                "fields": {**identity, "toolCallId": "call-1", "toolName": "git_status_tool"},
            },
            {
                "event_code": "session.assistant_delta.published",
                "outcome": "observed",
                "ts": "2026-07-15T01:00:04Z",
                "fields": identity,
            },
            {
                "event_code": "conversation.turn.result",
                "outcome": "succeeded",
                "ts": "2026-07-15T01:00:06Z",
                "fields": identity,
            },
        ],
    )
    _write_jsonl(
        scene / "events" / "llm.jsonl",
        [
            {
                "event_code": "llm.stream.started",
                "outcome": "started",
                "ts": "2026-07-15T01:00:01Z",
                "fields": identity,
            },
            {
                "event_code": "llm.stream.succeeded",
                "outcome": "succeeded",
                "ts": "2026-07-15T01:00:05Z",
                "fields": identity,
            },
        ],
    )
    _write_jsonl(
        scene / "events" / "browser_page.jsonl",
        [
            {
                "event_code": "browser.session_stream.assistant_delta_applied",
                "outcome": "observed",
                "ts": "2026-07-15T01:00:04Z",
                "fields": identity,
            },
            {
                "event_code": "browser.session_stream.snapshot_applied",
                "outcome": "succeeded",
                "ts": "2026-07-15T01:00:07Z",
                "fields": identity,
            },
        ],
    )
    _write_jsonl(
        scene / "timeline.jsonl",
        [
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2026-07-15T01:00:00Z",
                "fields": identity,
            }
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(
        log_path=str(scene),
        session_id="session-1",
        turn_id="turn-1",
    )

    trace = result["inspections"][0]["agentTrace"]
    assert trace["status"] == "completed"
    assert trace["traceId"] == "turn-1"
    assert trace["currentStage"] == "completed"
    assert trace["durationMs"] == 7000
    assert trace["llm"] == {"attemptCount": 1, "eventCount": 2, "retryCount": 0}
    assert trace["tools"] == {"callCount": 1, "names": ["git_status_tool"]}
    assert trace["delivery"] == {
        "publishedDeltaCount": 1,
        "appliedDeltaCount": 1,
        "snapshotApplied": True,
    }
    assert trace["anomalies"] == []
    assert {item["eventCode"] for item in trace["evidenceRefs"]} == {
        "conversation.turn.started",
        "llm.stream.started",
        "conversation.turn.tool_call",
        "session.assistant_delta.published",
        "browser.session_stream.assistant_delta_applied",
        "llm.stream.succeeded",
        "conversation.turn.result",
        "browser.session_stream.snapshot_applied",
    }
    assert len(trace["evidenceRefs"]) == 8
    assert "content" not in json.dumps(trace, ensure_ascii=False).lower()


def test_agent_trace_marks_only_stale_running_turns_without_calling_them_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(conversation_log_tools, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(conversation_log_tools, "LOG_INFO_DIR", tmp_path / "log_info")
    scene = tmp_path / "logs" / "runtime_scenes" / "scene-stalled"
    (scene / "manifest.json").parent.mkdir(parents=True)
    (scene / "manifest.json").write_text(json.dumps({"runtime_scene_id": "scene-stalled"}), encoding="utf-8")
    _write_jsonl(
        scene / "events" / "conversation.jsonl",
        [
            {
                "event_code": "conversation.turn.started",
                "outcome": "started",
                "ts": "2020-01-01T00:00:00Z",
                "fields": {"sessionId": "session-stalled", "turnId": "turn-stalled"},
            },
            {
                "event_code": "conversation.turn.llm_status_server_thinking",
                "outcome": "observed",
                "ts": "2020-01-01T00:00:01Z",
                "fields": {"sessionId": "session-stalled", "turnId": "turn-stalled"},
            },
        ],
    )

    result = conversation_log_tools.inspect_conversation_logs(
        log_path=str(scene),
        session_id="session-stalled",
        turn_id="turn-stalled",
    )

    trace = result["inspections"][0]["agentTrace"]
    assert trace["status"] == "running"
    assert trace["currentStage"] == "waiting_for_model"
    assert trace["stall"]["detected"] is True
    assert trace["stall"]["lastEventCode"] == "conversation.turn.llm_status_server_thinking"
    assert trace["stall"]["idleMs"] >= 20_000
    assert "stall" in trace["anomalies"]
    assert "runtime_error" not in trace["anomalies"]
