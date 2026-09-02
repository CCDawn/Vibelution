import json
from types import SimpleNamespace

import pytest

from tests.test_agent_config_workspace_service import (
    ProviderConfig,
    _fake_config_workspace,
    _mark_config_agent_instances_present,
    _raw_mode_binding,
    _seed_supervised_fixed_role_agent,
    _use_tmp_project_root,
    agent_bulk_delete_service,
    agent_config_workspace_service,
    agent_directory_service,
    agent_mode_binding_service,
    agent_tool_governance_service,
    agents_route,
    chat_room_service,
    client,
    config_package,
    config_service,
    context_engine,
    prompt_template_service,
    self_evolution_control_service,
    session_service,
    supervised_agent_service,
    team_service,
)

def test_agent_patch_memory_policy_updates_private_policy_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="记忆 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "memoryPolicy": {
                "readSharedGroups": ["project", "research"],
                "writeSharedGroups": ["project"],
                "readKnowledgeBaseIds": ["kb-research"],
                "proposeKnowledgeBaseIds": ["kb-research"],
                "reviewKnowledgeBaseIds": ["kb-review"],
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["memoryPolicyId"] == f"memory-{agent['agentId']}"
    assert payload["memoryPolicy"]["readSharedGroups"] == ["project", "research"]
    assert payload["memoryPolicy"]["writeSharedGroups"] == ["project"]
    assert payload["memoryPolicy"]["readKnowledgeBaseIds"] == ["kb-research"]
    assert payload["memoryPolicy"]["proposeKnowledgeBaseIds"] == ["kb-research"]
    assert payload["memoryPolicy"]["reviewKnowledgeBaseIds"] == ["kb-review"]
    assert payload["memoryPolicy"]["privateMemoryRoot"].endswith("/memory")
    assert any(
        event[0][:3] == ("agent_directory", "memory_policy", "agent.memory_policy.updated")
        and event[1]["fields"]["readSharedGroupCount"] == 2
        and event[1]["fields"]["writeSharedGroupCount"] == 1
        and event[1]["fields"]["readKnowledgeBaseCount"] == 1
        and event[1]["fields"]["reviewKnowledgeBaseCount"] == 1
        for event in recorded_events
    )
    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])
    assert "TeamKnowledgeAccess:" in context_block
    assert "ReadKnowledgeBaseIds: kb-research" in context_block
    assert "Knowledge bodies are tool-readable only" in context_block


def test_agent_runtime_context_without_knowledge_policy_renders_guidance_not_placeholder_ids(tmp_path, monkeypatch):
    from core.web.services import team_knowledge_service as team_knowledge_service_mod

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_knowledge_service_mod, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="无知识库策略 Agent")

    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])

    assert "TeamKnowledgeAccess:" in context_block
    # 历史 bug：空策略会渲染占位符字面量，agent 照抄进 knowledge 工具后按精确 ID 匹配必然失败。
    assert "team-membership" not in context_block
    assert "team-review-roles" not in context_block
    propose_line = next(line for line in context_block.splitlines() if line.startswith("- ProposeKnowledgeBaseIds:"))
    assert "未配置提案知识库" in propose_line
    assert "不要猜测" in propose_line
    read_line = next(line for line in context_block.splitlines() if line.startswith("- ReadKnowledgeBaseIds:"))
    assert "未配置可读知识库" in read_line
    review_line = next(line for line in context_block.splitlines() if line.startswith("- ReviewKnowledgeBaseIds:"))
    assert "未配置审核知识库" in review_line
    rate_line = next(line for line in context_block.splitlines() if line.startswith("- RateKnowledgeBaseIds:"))
    assert "未配置评分知识库" in rate_line


def test_agent_runtime_context_resolves_team_knowledge_base_ids_when_policy_empty(tmp_path, monkeypatch):
    from core.web.services import team_knowledge_service as team_knowledge_service_mod

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_knowledge_service_mod, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="团队知识 Agent")
    team = team_service.create_team(
        name="知识扩充团队",
        members=[{"agentId": agent["agentId"], "role": "member", "agentName": "团队知识 Agent"}],
    )
    knowledge_base = team_knowledge_service_mod.create_knowledge_base(
        team["teamId"],
        name="Knowledge Expansion Library",
        actor_agent_id=agent["agentId"],
    )
    scoped_id = str(knowledge_base.get("scopedKnowledgeBaseId") or "").strip()
    assert scoped_id.startswith("team:")

    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])

    assert "team-membership" not in context_block
    read_line = next(line for line in context_block.splitlines() if line.startswith("- ReadKnowledgeBaseIds:"))
    assert scoped_id in read_line
    propose_line = next(line for line in context_block.splitlines() if line.startswith("- ProposeKnowledgeBaseIds:"))
    assert scoped_id in propose_line
    assert "未配置提案知识库" not in propose_line


def test_agent_runtime_context_keeps_explicit_knowledge_policy_ids_unchanged(tmp_path, monkeypatch):
    from core.web.services import team_knowledge_service as team_knowledge_service_mod

    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(team_knowledge_service_mod, "PROJECT_ROOT", tmp_path)
    agent = agent_directory_service.create_agent_instance(display_name="显式策略 Agent")
    team = team_service.create_team(
        name="知识扩充团队",
        members=[{"agentId": agent["agentId"], "role": "member", "agentName": "显式策略 Agent"}],
    )
    knowledge_base = team_knowledge_service_mod.create_knowledge_base(
        team["teamId"],
        name="Knowledge Expansion Library",
        actor_agent_id=agent["agentId"],
    )
    scoped_id = str(knowledge_base.get("scopedKnowledgeBaseId") or "").strip()

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "memoryPolicy": {
                "readSharedGroups": ["project"],
                "writeSharedGroups": [],
                "readKnowledgeBaseIds": ["kb-research"],
                "proposeKnowledgeBaseIds": ["kb-research"],
                "reviewKnowledgeBaseIds": [],
                "rateKnowledgeBaseIds": [],
            }
        },
    )
    assert response.status_code == 200, response.text

    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])

    # 非空策略路径保持原样：显式 ID 原样渲染，不被解析结果覆盖。
    assert "ReadKnowledgeBaseIds: kb-research" in context_block
    propose_line = next(line for line in context_block.splitlines() if line.startswith("- ProposeKnowledgeBaseIds:"))
    assert "kb-research" in propose_line
    assert scoped_id not in propose_line
    assert "team-membership" not in context_block


def test_project_memory_update_proposals_are_agent_private_and_resolvable(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    alpha = agent_directory_service.create_agent_instance(
        display_name="运行主干 Agent",
        direct_session_id="session-alpha",
    )
    beta = agent_directory_service.create_agent_instance(
        display_name="前端 Agent",
        direct_session_id="session-beta",
    )

    first = agent_directory_service.write_project_memory_update_proposal(
        alpha["agentId"],
        lane_id="agent-runtime-core",
        focus="memory proposal queue",
        update="Add a serialized project-memory proposal queue.",
        related_files=["core/web/services/agent_directory_service.py"],
        source_turn_id="turn-alpha",
    )
    second = agent_directory_service.write_project_memory_update_proposal(
        beta["agentId"],
        lane_id="web-workbench-surface",
        update="Surface pending memory proposals in Agent Center later.",
    )

    proposal_path = tmp_path / "workspace" / "agents" / alpha["agentId"] / "events" / "project_memory_updates.jsonl"
    assert proposal_path.exists()
    assert agent_directory_service.resolve_memory_policy_for_agent(alpha["agentId"])[
        "projectMemoryUpdatesPath"
    ] == f"workspace/agents/{alpha['agentId']}/events/project_memory_updates.jsonl"
    pending = agent_directory_service.list_project_memory_update_proposals(status="pending")
    assert [item["proposalId"] for item in pending] == [first["proposalId"], second["proposalId"]]

    resolved = agent_directory_service.resolve_project_memory_update_proposal(
        alpha["agentId"],
        first["proposalId"],
        status="applied",
        resolved_by="coordinator",
        resolution_note="Merged into agent-runtime-core lane.",
    )

    assert resolved["status"] == "applied"
    assert resolved["resolvedBy"] == "coordinator"
    assert agent_directory_service.list_project_memory_update_proposals(status="pending") == [second]
    context_block = agent_directory_service.build_agent_runtime_context_block(alpha["agentId"])
    assert "ProjectMemoryUpdatesPath:" in context_block
    assert any(
        event[0][:3] == ("agent_memory", "events", "project_memory_update.proposed")
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("agent_memory", "events", "project_memory_update.resolved")
        for event in recorded_events
    )


def test_project_memory_update_proposal_routes_queue_and_resolve(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(
        display_name="协同 Agent",
        direct_session_id="session-memory-proposal",
    )

    created = client.post(
        f"/api/agents/{agent['agentId']}/project-memory-updates",
        json={
            "laneId": "agent-runtime-core",
            "focus": "proposal queue",
            "update": "Record project-memory changes as per-Agent proposals.",
            "details": "Coordinator will merge these proposals serially.",
            "relatedFiles": ["AGENTS.md"],
            "sourceTurnId": "turn-1",
        },
    )

    assert created.status_code == 201, created.text
    proposal = created.json()
    assert proposal["status"] == "pending"
    listed = client.get("/api/agents/project-memory-updates")
    assert listed.status_code == 200, listed.text
    assert [item["proposalId"] for item in listed.json()] == [proposal["proposalId"]]

    resolved = client.patch(
        f"/api/agents/{agent['agentId']}/project-memory-updates/{proposal['proposalId']}",
        json={
            "status": "rejected",
            "resolvedBy": "coordinator",
            "resolutionNote": "Duplicate proposal.",
        },
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"
    assert client.get("/api/agents/project-memory-updates").json() == []
    all_items = client.get("/api/agents/project-memory-updates", params={"status": ""}).json()
    assert all_items[0]["status"] == "rejected"


def test_agent_patch_runtime_policies_updates_metadata_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="运行策略 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "delegationPolicy": {
                "allowSubagents": True,
                "maxConcurrent": 99,
                "maxDepth": 9,
                "allowWakeMessages": False,
                "allowedContextModes": ["fork", "invalid", "isolated"],
            },
            "supervisionPolicy": {
                "supervisionEnabled": True,
                "requiresReview": True,
                "reviewMode": "required",
                "evidenceLevel": "strict",
            },
        },
    )

    assert response.status_code == 200, response.text
    metadata = response.json()["metadata"]
    assert metadata["delegationPolicy"] == {
        "allowSubagents": True,
        "maxConcurrent": 8,
        "maxDepth": 4,
        "allowWakeMessages": False,
        "allowedContextModes": ["fork", "isolated"],
    }
    assert metadata["supervisionPolicy"] == {
        "supervisionEnabled": True,
        "requiresReview": True,
        "reviewMode": "required",
        "evidenceLevel": "strict",
    }
    assert any(
        event[0][:3] == ("agent_directory", "delegation_policy", "agent.delegation_policy.updated")
        and event[1]["fields"]["allowSubagents"] is True
        and event[1]["fields"]["maxConcurrent"] == 8
        and event[1]["fields"]["maxDepth"] == 4
        and event[1]["fields"]["allowedContextModeCount"] == 2
        for event in recorded_events
    )
    assert any(
        event[0][:3] == ("agent_directory", "supervision_policy", "agent.supervision_policy.updated")
        and event[1]["fields"]["supervisionEnabled"] is True
        and event[1]["fields"]["requiresReview"] is True
        and event[1]["fields"]["reviewMode"] == "required"
        and event[1]["fields"]["evidenceLevel"] == "strict"
        for event in recorded_events
    )


def test_agent_runtime_context_does_not_inject_tool_policy_summary(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="能力管家")
    agent_directory_service.update_agent_instance(
        agent["agentId"],
        tool_policy={
            "allowedTools": [
                "agent_message_tool",
                "research_knowledge_query_tool",
                "read_memory_tool",
                "get_memory_summary_tool",
                "read_dynamic_prompt_tool",
            ],
            "preferredTools": ["read_memory_tool", "research_knowledge_query_tool"],
        },
    )

    context_block = agent_directory_service.build_agent_runtime_context_block(agent["agentId"])

    assert "ToolPolicy:" not in context_block
    assert "visible=agent_message_tool, research_knowledge_query_tool" not in context_block
    assert "configuredUnavailableCount=3" not in context_block
    assert "agent_message_tool" not in context_block
    assert "research_knowledge_query_tool" not in context_block
    assert "read_memory_tool" not in context_block
    assert "get_memory_summary_tool" not in context_block
    assert "read_dynamic_prompt_tool" not in context_block
    assert "preferred=research_knowledge_query_tool" not in context_block
