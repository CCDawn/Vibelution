"""Memory operation telemetry must cover rejection without copying content."""

import json
import logging

import pytest

from core.web.services import agent_directory_service, runtime_scene_service, team_knowledge_service
from tools import episodic_memory_tools, team_knowledge_tools


@pytest.fixture
def runtime():
    return {
        "agentId": "agent-audit-owner",
        "sessionId": "session-audit",
        "turnId": "turn-audit",
        "toolCallId": "call-audit",
        "memoryPolicy": {"enabled": False},
    }


@pytest.fixture
def events(monkeypatch):
    captured = []

    def record(component, phase, event_code, **kwargs):
        captured.append({"component": component, "phase": phase, "eventCode": event_code, **kwargs})
        return {"accepted": True}

    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", record)
    return captured


def test_disabled_private_search_records_correlated_denial(monkeypatch, runtime, events):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    result = json.loads(team_knowledge_tools.search_agent_private_memory_tool(query="PRIVATE-CONTENT-MARKER"))
    assert result["error"] == "personal_memory_disabled"
    event = next(event for event in events if event["eventCode"] == "memory.tool.execution.blocked")
    assert event["fields"]["reasonCode"] == "personal_memory_disabled"
    assert event["fields"]["agentId"] == runtime["agentId"]
    assert event["fields"]["sessionId"] == runtime["sessionId"]
    assert event["fields"]["turnId"] == runtime["turnId"]
    assert event["fields"]["toolCallId"] == runtime["toolCallId"]
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


def test_missing_agent_records_blocked_personal_write(monkeypatch, events):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: {})
    result = json.loads(episodic_memory_tools.append_personal_memory_tool(text="PRIVATE-CONTENT-MARKER"))
    assert result["error"] == "agent_runtime_missing"
    event = next(event for event in events if event["eventCode"] == "memory.tool.execution.blocked")
    assert event["fields"]["toolName"] == "append_personal_memory_tool"
    assert event["fields"]["reasonCode"] == "agent_runtime_missing"
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


def test_personal_write_failure_records_class_not_exception_text(monkeypatch, runtime, events):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)

    def fail(*args, **kwargs):
        raise OSError("PRIVATE-ERROR-MARKER")

    monkeypatch.setattr(agent_directory_service, "append_episodic_event", fail)
    result = json.loads(episodic_memory_tools.append_personal_memory_tool(text="PRIVATE-CONTENT-MARKER"))
    assert result["error"] == "OSError"
    event = next(event for event in events if event["eventCode"] == "memory.tool.execution.failed")
    assert event["fields"]["reasonCode"] == "OSError"
    assert event["fields"]["durationMs"] >= 0
    assert "PRIVATE-ERROR-MARKER" not in json.dumps(events)
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


def test_personal_success_records_episode_identity(monkeypatch, runtime, events):
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    monkeypatch.setattr(agent_directory_service, "append_episodic_event", lambda *args, **kwargs: {
        "episodeId": "episode-audit", "agentId": runtime["agentId"], "kind": "note", "validUntil": "",
    })
    result = json.loads(episodic_memory_tools.append_personal_memory_tool(text="PRIVATE-CONTENT-MARKER"))
    assert result["status"] == "appended"
    event = next(event for event in events if event["eventCode"] == "memory.tool.execution.succeeded")
    assert event["fields"]["episodeId"] == "episode-audit"
    assert event["fields"]["sessionId"] == runtime["sessionId"]
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


@pytest.mark.parametrize("owner", ["personal", "knowledge", "tool"])
def test_existing_memory_event_writers_alert_when_sink_fails(monkeypatch, caplog, owner):
    def fail(*args, **kwargs):
        raise OSError("PRIVATE-ERROR-MARKER")

    if owner == "personal":
        monkeypatch.setattr(agent_directory_service, "record_runtime_scene_event", fail)
        emit = lambda: agent_directory_service._record_memory_event(
            "episodic_event.appended", {"eventId": "episode-audit"}, agent_id="agent-audit-owner")
    elif owner == "knowledge":
        monkeypatch.setattr(team_knowledge_service, "record_runtime_scene_event", fail)
        emit = lambda: team_knowledge_service._record_event(
            "knowledge.proposal.created", {"ownerType": "agent", "ownerId": "agent-audit-owner"}, "kb-audit")
    else:
        monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fail)
        emit = lambda: team_knowledge_tools._record_event(
            "knowledge.tool.read", runtime={"agentId": "agent-audit-owner", "sessionId": "session-audit"})
    with caplog.at_level(logging.WARNING):
        emit()
    assert "memory.event.write_failed" in caplog.text
    assert "OSError" in caplog.text
    assert "PRIVATE-ERROR-MARKER" not in caplog.text


@pytest.mark.parametrize("error", [
    team_knowledge_service.TeamKnowledgePermissionError("PRIVATE-ERROR-MARKER"),
    OSError("PRIVATE-ERROR-MARKER"),
])
def test_source_lifecycle_failure_preserves_response_and_hides_free_text(monkeypatch, runtime, events, error):
    runtime["memoryPolicy"] = {"enabled": True, "reviewKnowledgeBaseIds": ["kb-audit"]}
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(team_knowledge_service, "set_knowledge_source_lifecycle", fail)
    result = json.loads(team_knowledge_tools.knowledge_source_lifecycle_tool(
        "kb-audit", "src-audit", "withdrawn", "PRIVATE-CONTENT-MARKER"))
    denied = isinstance(error, team_knowledge_service.TeamKnowledgePermissionError)
    assert result["status"] == ("blocked" if denied else "failed")
    event = next(event for event in events if event["eventCode"] ==
                 f"memory.tool.execution.{'blocked' if denied else 'failed'}")
    assert event["fields"]["knowledgeBaseId"] == "kb-audit"
    assert event["fields"]["sourceArtifactId"] == "src-audit"
    assert event["fields"]["reasonCode"] == ("knowledge_access_denied" if denied else "operation_failed")
    assert "PRIVATE-ERROR-MARKER" not in json.dumps(events)
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


def test_invalid_proposal_parameters_are_logged_without_content(monkeypatch, runtime, events):
    runtime["memoryPolicy"] = {"enabled": True, "proposeKnowledgeBaseIds": ["kb-audit"]}
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    result = json.loads(team_knowledge_tools.knowledge_proposal_tool(
        "kb-audit", "agent_authored", "PRIVATE-CONTENT-MARKER", "title", "PRIVATE-CONTENT-MARKER"))
    assert result["error"] == "invalid_json"
    event = next(event for event in events if event["eventCode"] == "memory.tool.execution.failed")
    assert event["fields"]["reasonCode"] == "invalid_json"
    assert event["fields"]["knowledgeBaseId"] == "kb-audit"
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(events)


def test_logging_failure_does_not_retry_or_fail_successful_personal_write(monkeypatch, runtime, caplog):
    from core.logging import memory_events
    from core.logging.pipeline_metrics import LoggingPipelineMetrics

    metrics = LoggingPipelineMetrics()
    monkeypatch.setattr(memory_events, "pipeline_metrics", metrics)
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    writes = []

    def append(*args, **kwargs):
        writes.append(kwargs["text"])
        return {"episodeId": "episode-audit", "agentId": runtime["agentId"], "kind": "note"}

    def fail(*args, **kwargs):
        raise OSError("PRIVATE-ERROR-MARKER")

    monkeypatch.setattr(agent_directory_service, "append_episodic_event", append)
    monkeypatch.setattr(runtime_scene_service, "record_runtime_scene_event", fail)
    with caplog.at_level(logging.WARNING):
        result = json.loads(episodic_memory_tools.append_personal_memory_tool(text="PRIVATE-CONTENT-MARKER"))
    assert result["status"] == "appended"
    assert writes == ["PRIVATE-CONTENT-MARKER"]
    assert metrics.snapshot()["drops"]["operational:writer_failed"] == 1
    assert "memory.event.write_failed" in caplog.text
    assert "PRIVATE-CONTENT-MARKER" not in caplog.text
    assert "PRIVATE-ERROR-MARKER" not in caplog.text


def test_broken_warning_handler_does_not_raise_or_recurse(monkeypatch):
    from core.logging import memory_events
    from core.logging.pipeline_metrics import LoggingPipelineMetrics

    metrics = LoggingPipelineMetrics()
    monkeypatch.setattr(memory_events, "pipeline_metrics", metrics)
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        raise OSError("PRIVATE-ERROR-MARKER")

    monkeypatch.setattr(memory_events._logger, "warning", fail)
    memory_events.record_memory_event("agent_memory", "events", "episodic_event.appended",
                                      fields={}, writer=fail)
    assert calls == [1, 1]
    assert metrics.snapshot()["drops"]["operational:writer_failed"] == 1


def test_executor_propagates_call_identity_without_runtime_injection(monkeypatch, runtime, events):
    from core.infrastructure.tool_executor import ToolExecutor

    runtime.pop("toolCallId")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    executor = ToolExecutor()
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *args, **kwargs: None)
    result, _ = executor.execute("search_agent_private_memory_tool", {"query": "PRIVATE-CONTENT-MARKER"},
                                 tool_call_id="call-native-memory")
    assert json.loads(result)["status"] == "blocked"
    event = next(row for row in events if row["eventCode"] == "memory.tool.execution.blocked")
    assert event["fields"]["toolCallId"] == "call-native-memory"
    assert event["fields"]["sessionId"] == runtime["sessionId"]
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps([row for row in events
                                                       if row["eventCode"].startswith("memory.")])
    events.clear()
    team_knowledge_tools.search_agent_private_memory_tool()
    event = next(row for row in events if row["eventCode"] == "memory.tool.execution.blocked")
    assert "toolCallId" not in event["fields"]


def test_parallel_executor_memory_calls_do_not_share_call_identity(monkeypatch, runtime, events):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from core.infrastructure.tool_executor import ToolExecutor

    runtime.pop("toolCallId")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    barrier = Barrier(2)

    def append(*args, **kwargs):
        barrier.wait(timeout=5)
        return {"episodeId": "episode-" + kwargs["text"], "agentId": runtime["agentId"], "kind": "note"}

    monkeypatch.setattr(agent_directory_service, "append_episodic_event", append)
    executor = ToolExecutor()
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *args, **kwargs: None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(executor.execute, "append_personal_memory_tool", {"text": marker},
                               tool_call_id="call-" + marker) for marker in ("first", "second")]
        assert all(json.loads(future.result(timeout=10)[0])["ok"] for future in futures)
    terminal = [row for row in events if row["eventCode"] == "memory.tool.execution.succeeded"]
    assert {(row["fields"]["toolCallId"], row["fields"]["episodeId"]) for row in terminal} == {
        ("call-first", "episode-first"), ("call-second", "episode-second")}


@pytest.mark.parametrize("outcome", ["blocked", "failed"])
def test_terminal_audit_does_not_refresh_full_scene_on_request(tmp_path, monkeypatch, runtime, outcome):
    from tests.test_runtime_scene_projection_fastpath import _point_runtime_scene_at

    scene = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-memory-audit-fastpath")
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: runtime)
    monkeypatch.setattr(runtime_scene_service, "_scene_package_refresh_window_open", lambda *args: True)
    full_refreshes = []
    monkeypatch.setattr(runtime_scene_service, "_update_runtime_scene_package_manifest",
                        lambda *args, **kwargs: full_refreshes.append(1))
    if outcome == "blocked":
        result = json.loads(team_knowledge_tools.search_agent_private_memory_tool())
    else:
        def fail(*args, **kwargs):
            raise OSError("PRIVATE-ERROR-MARKER")
        monkeypatch.setattr(agent_directory_service, "append_episodic_event", fail)
        result = json.loads(episodic_memory_tools.append_personal_memory_tool("PRIVATE-CONTENT-MARKER"))
    assert result["status"] == outcome
    rows = [json.loads(line) for path in (scene / "events").glob("*.jsonl")
            for line in path.read_text(encoding="utf8").splitlines() if line.strip()]
    assert any(row["event_code"] == "memory.tool.execution." + outcome for row in rows)
    assert full_refreshes == []


def test_real_memory_operations_persist_safe_correlated_runtime_events(tmp_path, monkeypatch):
    from core.infrastructure.tool_executor import ToolExecutor
    from tests.test_runtime_scene_projection_fastpath import _point_runtime_scene_at

    monkeypatch.setenv("VIBELUTION_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    scene = _point_runtime_scene_at(tmp_path, monkeypatch, scene_id="scene-memory-audit")
    agent = agent_directory_service.create_agent_instance(display_name="Memory audit owner")
    bound = {"agentId": agent["agentId"], "sessionId": "session-audit",
             "turnId": "turn-audit", "memoryPolicy": {"enabled": True}}
    monkeypatch.setattr(agent_directory_service, "current_agent_runtime", lambda: bound)
    executor = ToolExecutor()
    monkeypatch.setattr(executor, "_check_canonical_execution_authorization", lambda *args, **kwargs: None)
    monkeypatch.setattr(executor, "_check_runtime_block", lambda *args, **kwargs: None)
    def execute(name, args, call_id):
        return json.loads(executor.execute(name, args, tool_call_id=call_id)[0])
    written = execute("append_personal_memory_tool", {"text": "PRIVATE-CONTENT-MARKER"}, "call-append")
    assert written["ok"] is True
    invalidated = execute("supersede_personal_memory_tool", {"episode_id": written["episodeId"]}, "call-supersede")
    assert invalidated["status"] == "superseded"
    assert agent_directory_service.list_current_episodic_events(agent["agentId"]) == []
    bound["memoryPolicy"]["enabled"] = False
    rejected = execute("search_agent_private_memory_tool", {"query": "PRIVATE-CONTENT-MARKER"}, "call-blocked")
    assert rejected["status"] == "blocked"
    rows = [json.loads(line) for path in (scene / "events").glob("*.jsonl")
            for line in path.read_text(encoding="utf8").splitlines() if line.strip()]
    terminal = [row for row in rows if row.get("event_code", "").startswith("memory.tool.execution.")]
    assert len(terminal) == 3
    assert {row["fields"]["toolName"] for row in terminal} == {
        "append_personal_memory_tool", "supersede_personal_memory_tool", "search_agent_private_memory_tool"}
    assert all(row["fields"]["sessionId"] == "session-audit" for row in terminal)
    assert all(row["fields"]["turnId"] == "turn-audit" for row in terminal)
    assert {row["fields"]["toolCallId"] for row in terminal} == {"call-append", "call-supersede", "call-blocked"}
    appended = next(row for row in terminal if row["fields"]["toolName"] == "append_personal_memory_tool")
    assert appended["fields"]["episodeId"] == written["episodeId"]
    assert "PRIVATE-CONTENT-MARKER" not in json.dumps(rows)
