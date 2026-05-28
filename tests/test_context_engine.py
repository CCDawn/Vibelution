import json

from core.orchestration import context_engine
from core.runtime_manager import work_run_store
from core.web.services import agent_directory_service, prompt_template_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)


def test_build_agent_context_collects_isolated_agent_runtime_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="科研广搜 Agent",
        profile_id="research_broad",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-research",
    )
    agent_directory_service.write_group_context_event(
        agent["agentId"],
        {
            "sourceRoomId": "room-1",
            "sourceRoundId": "round-1",
            "topic": "统一配置",
            "summary": "模型与提示词分层",
            "ownMessage": "我负责广搜。",
            "peerHighlights": ["评审 Agent 发现兼容层风险"],
        },
    )
    agent_directory_service.write_agent_inbox_message(
        agent["agentId"],
        content="请检查 ModeBinding 是否还在读旧字段。",
        summary="检查 ModeBinding 旧字段",
        created_by="test",
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-research", run_id="turn-1")

    assert packet.agent_id == agent["agentId"]
    assert packet.agent_code == "A001"
    assert packet.profile_id == "research_broad"
    assert packet.prompt_template_id == "prompt-research-broad"
    assert packet.role_key == "research_broad"
    assert packet.workspace_path == agent["workspacePath"]
    assert packet.memory_policy["privateMemoryRoot"].endswith("/memory")
    assert packet.tool_policy["policyId"]
    assert len(packet.group_context_events) == 1
    assert len(packet.inbox_messages) == 1
    assert "Agent Runtime Context" in packet.context_block
    assert "检查 ModeBinding 旧字段" in packet.context_block
    assert "Agent Prompt Template" in packet.context_block
    assert "prompt-research-broad" in packet.context_block
    assert "广撒网探索 agent" in packet.context_block


def test_build_agent_context_returns_empty_packet_for_missing_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    packet = context_engine.build_agent_context("missing-agent", session_id="session-missing")

    assert packet.agent_id == "missing-agent"
    assert packet.session_id == "session-missing"
    assert packet.context_block == ""
    assert packet.memory_policy == {}
    assert packet.tool_policy == {}


def test_prepare_subagent_spawn_isolated_by_default_and_fork_is_explicit(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = agent_directory_service.create_agent_instance(
        display_name="父 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-parent",
        metadata={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxDepth": 2,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated", "fork"],
            }
        },
    )

    isolated = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="isolated",
    )
    forked = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="fork",
    )

    assert isolated.parent_context is None
    assert forked.parent_context is not None
    assert forked.parent_context.agent_id == parent["agentId"]


def test_prepare_subagent_spawn_respects_delegation_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    parent = agent_directory_service.create_agent_instance(
        display_name="受控父 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-parent",
        metadata={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxDepth": 1,
                "maxConcurrent": 1,
                "allowWakeMessages": True,
                "allowedContextModes": ["isolated"],
            }
        },
    )

    allowed = context_engine.prepare_subagent_spawn(
        parent["agentId"],
        "session-parent",
        context_mode="isolated",
        requested_depth=1,
    )

    assert allowed.context_mode == "isolated"
    try:
        context_engine.prepare_subagent_spawn(
            parent["agentId"],
            "session-parent",
            context_mode="fork",
            requested_depth=1,
        )
    except ValueError as exc:
        assert "fork" in str(exc)
    else:
        raise AssertionError("Expected disallowed context mode to be blocked")
    try:
        context_engine.prepare_subagent_spawn(
            parent["agentId"],
            "session-parent",
            context_mode="isolated",
            requested_depth=2,
        )
    except ValueError as exc:
        assert "深度" in str(exc) or "depth" in str(exc).lower()
    else:
        raise AssertionError("Expected max depth to be blocked")


def test_record_agent_turn_result_writes_bounded_agent_event(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="会话 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-live",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-live",
        {
            "status": "completed",
            "summary": "line1\nline2\nline3\nline4\nline5",
            "tool_call_count": 2,
        },
        run_id="session-live-turn-1",
    )

    event_path = tmp_path / agent["workspacePath"] / "events" / "agent_turn_results.jsonl"
    records = [
        json.loads(line)
        for line in event_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["agentId"] == agent["agentId"]
    assert records[0]["sessionId"] == "session-live"
    assert records[0]["status"] == "completed"
    assert records[0]["toolCallCount"] == 2
    assert records[0]["summary"] == "line1\nline2\nline3\nline4"

    run_path = (
        work_run_store.WORK_RUNS_DIR
        / context_engine.AGENT_RUN_KIND
        / "runs"
        / f"agentrun-{agent['agentId']}-session-live-turn-1.json"
    )
    snapshot = json.loads(run_path.read_text(encoding="utf-8"))
    assert snapshot["runKind"] == "agent_run"
    assert snapshot["sourceRunId"] == "session-live-turn-1"
    assert snapshot["agentId"] == agent["agentId"]
    assert snapshot["agentCode"] == agent["agentCode"]
    assert snapshot["primaryMode"] == "chat"
    assert snapshot["profileId"] == "primary"
    assert snapshot["promptTemplateId"] == "prompt-chat-default"
    assert snapshot["workspacePath"] == agent["workspacePath"]
    assert snapshot["sessionId"] == "session-live"
    assert snapshot["status"] == "completed"
    assert snapshot["toolCallCount"] == 2
    assert snapshot["summary"] == "line1\nline2\nline3\nline4"
    assert "raw_output" not in snapshot
    assert "apiKey" not in json.dumps(snapshot)


def test_list_agent_runs_returns_bounded_safe_snapshots(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="运行历史 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-runs",
    )

    context_engine.record_agent_turn_result(
        agent["agentId"],
        "session-runs",
        {
            "status": "completed",
            "summary": "Authorization: Bearer sk-sensitive-token\nok",
            "raw_output": "full raw output should not be preferred",
            "tool_call_count": 1,
        },
        run_id="session-runs-turn-1",
    )
    context_engine.record_subagent_result(
        "session-runs-turn-1",
        "sub-1",
        {
            "status": "completed",
            "summary": "sub result",
            "parentAgentId": agent["agentId"],
            "parentSessionId": "session-runs",
            "contextMode": "isolated",
            "toolCallCount": 0,
        },
    )

    payload = context_engine.list_agent_runs_for_agent(agent["agentId"], limit=5)

    assert payload["agentId"] == agent["agentId"]
    assert payload["limit"] == 5
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["runKind"] == "agent_run"
    assert payload["runs"][0]["sourceRunId"] == "session-runs-turn-1"
    assert payload["runs"][0]["summary"] == "Authorization: Bearer ***\nok"
    assert "raw_output" not in payload["runs"][0]
    assert "metadata" not in payload["runs"][0]
    assert len(payload["subAgentRuns"]) == 1
    assert payload["subAgentRuns"][0]["runKind"] == "sub_agent_run"
    assert payload["subAgentRuns"][0]["parentRunId"] == "session-runs-turn-1"
    assert payload["subAgentRuns"][0]["parentAgentId"] == agent["agentId"]
