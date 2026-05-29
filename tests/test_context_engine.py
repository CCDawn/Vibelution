import json

from core.orchestration import context_engine
from core.runtime_manager import work_run_store
from core.web.services import agent_directory_service, prompt_template_service, research_organization_service


def _use_tmp_project_root(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_directory_service, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(prompt_template_service, "PROJECT_ROOT", tmp_path)


class _FakeResearchWorkspace:
    def __init__(self, root):
        self.root = root / "workspace"

    def get_research_organization_path(self):
        return self.root / "research" / "organization_graph.json"

    def read_research_organization(self):
        path = self.get_research_organization_path()
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def write_research_organization(self, data):
        path = self.get_research_organization_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True


def _use_tmp_research_org_workspace(tmp_path, monkeypatch):
    workspace = _FakeResearchWorkspace(tmp_path)
    monkeypatch.setattr(research_organization_service, "get_workspace", lambda: workspace)
    monkeypatch.setattr(research_organization_service, "record_research_scene_event", lambda *args, **kwargs: None)
    return workspace


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
    assert packet.timings["totalDurationMs"] >= 0
    assert "runtimeContextBlockMs" in packet.timings
    assert "promptTemplateContextMs" in packet.timings


def test_build_agent_context_includes_project_memory_coordination_rules_from_agents_md(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    (tmp_path / "AGENTS.md").write_text(
        "\n".join(
            [
                "# Test Rules",
                "",
                "## Session-Level Agent Memory Coordination",
                "",
                "- Session-level Agents may process project work in parallel.",
                "- Project memory is a single-writer shared record.",
                "- AGENTS.md is the default contract for this behavior.",
                "",
                "## Unrelated Section",
                "",
                "- This line must not enter the runtime context.",
            ]
        ),
        encoding="utf-8",
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="并行处理 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-parallel-memory",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-parallel-memory", run_id="turn-1")

    assert "Project Operating Rules" in packet.context_block
    assert "Session-level Agents may process project work in parallel." in packet.context_block
    assert "Project memory is a single-writer shared record." in packet.context_block
    assert "AGENTS.md is the default contract for this behavior." in packet.context_block
    assert "This line must not enter the runtime context." not in packet.context_block
    assert "projectRulesContextMs" in packet.timings
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.project_rules_context_loaded")
        and item[1]["fields"]["section"] == "Session-Level Agent Memory Coordination"
        for item in events
    )


def test_build_agent_context_includes_research_org_member_and_edge_context(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)

    organization = research_organization_service.get_research_organization()
    ceo = next(node for node in organization["agents"] if node["role"] == "ceo")
    advisor = next(node for node in organization["agents"] if node["role"] == "organization_advisor")
    steward = next(node for node in organization["agents"] if node["role"] == "capability_steward")

    packet = context_engine.build_agent_context(
        ceo["agentId"],
        session_id=ceo["agent"]["directSessionId"],
        run_id="turn-research-ceo",
    )

    assert "Research Organization Context" in packet.context_block
    assert ceo["agentCode"] in packet.context_block
    assert advisor["agentCode"] in packet.context_block
    assert steward["agentCode"] in packet.context_block
    assert ceo["agentId"] in packet.context_block
    assert advisor["agentId"] in packet.context_block
    assert steward["agentId"] in packet.context_block
    assert "Directly reachable from you:" in packet.context_block
    assert f"edge-{ceo['agentId']}-{advisor['agentId']}" in packet.context_block
    assert f"edge-{ceo['agentId']}-{steward['agentId']}" in packet.context_block
    assert "allowedTypes=" in packet.context_block
    assert "Use AgentId or AgentCode with agent_message_tool" in packet.context_block


def test_build_agent_context_filters_research_org_context_to_connected_subgraph(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    _use_tmp_research_org_workspace(tmp_path, monkeypatch)
    disconnected = agent_directory_service.create_agent_instance(
        display_name="旧研究员",
        primary_mode="research",
        role_key="research_specialist",
        prompt_template_id="prompt-research-broad",
        direct_session_id="session-old-specialist",
        metadata={"researchOrgRole": "research_specialist", "systemRole": "research_specialist"},
    )
    organization = research_organization_service.get_research_organization()
    ceo = next(node for node in organization["agents"] if node["role"] == "ceo")
    advisor = next(node for node in organization["agents"] if node["role"] == "organization_advisor")
    organization["agents"].append(
        {
            "nodeId": disconnected["agentId"],
            "agentId": disconnected["agentId"],
            "role": "research_specialist",
            "employeeRank": "member",
            "status": "active",
        }
    )
    research_organization_service.save_research_organization(organization)

    packet = context_engine.build_agent_context(
        ceo["agentId"],
        session_id=ceo["agent"]["directSessionId"],
        run_id="turn-research-ceo",
    )

    assert ceo["agentId"] in packet.context_block
    assert advisor["agentId"] in packet.context_block
    assert f"agentId={disconnected['agentId']} " not in packet.context_block


def test_build_agent_context_returns_empty_packet_for_missing_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    packet = context_engine.build_agent_context("missing-agent", session_id="session-missing")

    assert packet.agent_id == "missing-agent"
    assert packet.session_id == "session-missing"
    assert packet.context_block == ""
    assert packet.memory_policy == {}
    assert packet.tool_policy == {}


def test_build_agent_context_returns_empty_packet_for_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="已归档上下文 Agent",
        profile_id="primary",
        primary_mode="chat",
        direct_session_id="session-archived",
    )
    events = []
    monkeypatch.setattr(
        context_engine,
        "record_runtime_scene_event",
        lambda *args, **kwargs: events.append((args, kwargs)) or {"accepted": True},
    )

    agent_directory_service.archive_agent_instance(agent["agentId"])
    packet = context_engine.build_agent_context(agent["agentId"], session_id="session-archived")

    assert packet.agent_id == agent["agentId"]
    assert packet.session_id == "session-archived"
    assert packet.context_block == ""
    assert packet.memory_policy == {}
    assert packet.tool_policy == {}
    assert packet.timings["reason"] == "archived_agent"
    assert packet.timings["agentStatus"] == "archived"
    assert any(
        item[0][:3] == ("agent_context", "context_engine", "agent_runtime.resolve_failed")
        and item[1]["fields"]["reason"] == "archived_agent"
        and item[1]["fields"]["agentStatus"] == "archived"
        for item in events
    )


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
