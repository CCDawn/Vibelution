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

def test_agent_create_api_adds_direct_agent_with_safe_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "新增研究 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "research",
            "roleKey": "research_broad",
            "promptTemplateId": "prompt-research-broad",
            "personaProfile": {"personality": "冷静、细致，优先核对证据。"},
            "taskProfile": {"mission": "负责复核研究结论。", "taskTypes": ["research_broad"]},
            "toolPolicy": {"allowedTools": ["agent_message_tool"], "preferredTools": ["agent_message_tool"]},
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["agentId"]
    assert agent["displayName"]
    assert agent["displayName"] != "新增研究 Agent"
    assert agent["metadata"]["functionalDisplayName"] == "新增研究 Agent"
    assert agent["primaryMode"] == "research"
    assert agent["roleKey"] == "research_broad"
    assert agent["promptTemplateId"] == "prompt-research-broad"
    assert agent["directSessionId"]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    assert agent["agentId"] in {item["agentId"] for item in workspace["agents"]}
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["metadata"]["creationSpec"]["source"] == "api_agents"
    assert created["metadata"]["onboardingStatus"] == "complete"
    assert created["metadata"]["onboardingMissing"] == []
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])
    assert created["toolPolicy"]["allowedTools"] == ["agent_message_tool"]


def test_agent_create_api_allows_work_session_without_persona_task_or_role(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "项目实现会话",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["primaryMode"] == "chat"
    assert agent["roleKey"] == ""
    assert not agent_directory_service.agent_persona_profile_has_content(agent["personaProfile"])
    assert not agent_directory_service.agent_task_profile_has_content(agent["taskProfile"])
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["agentBoundary"]["type"] == "work_session"
    assert created["agentBoundary"]["requiresPersonaProfile"] == "false"
    assert created["agentBoundary"]["requiresTaskProfile"] == "false"
    assert created["toolPolicyId"].startswith("tool-")
    assert created["toolPolicy"]["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert created["toolPolicy"]["preferredTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    assert "read_file_tool" not in created["toolPolicy"]["allowedTools"]
    assert "grep_search_tool" in created["toolPolicy"]["allowedTools"]
    assert "glob_tool" in created["toolPolicy"]["allowedTools"]
    assert "cli_tool" in created["toolPolicy"]["allowedTools"]
    assert "run_test_for_tool" in created["toolPolicy"]["allowedTools"]
    assert "python_lint_tool" in created["toolPolicy"]["allowedTools"]
    assert "apply_patch_tool" in created["toolPolicy"]["allowedTools"]
    assert "write_file_tool" in created["toolPolicy"]["allowedTools"]
    assert "web_search_tool" not in created["toolPolicy"]["allowedTools"]
    assert "image2_generate_tool" not in created["toolPolicy"]["allowedTools"]
    assert "cli_agent_run_tool" not in created["toolPolicy"]["allowedTools"]
    assert "search_memory_tool" not in created["toolPolicy"]["allowedTools"]
    assert "search_error_archive_tool" not in created["toolPolicy"]["allowedTools"]
    assert "record_learning_tool" not in created["toolPolicy"]["allowedTools"]
    assert "code_symbol_tool" in created["toolPolicy"]["allowedTools"]
    assert "research_knowledge_query_tool" not in created["toolPolicy"]["allowedTools"]
    assert "knowledge_proposal_tool" not in created["toolPolicy"]["allowedTools"]
    assert "research_agent_creation_proposal_tool" not in created["toolPolicy"]["allowedTools"]
    assert "create_child_session_tool" not in created["toolPolicy"]["allowedTools"]
    assert "list_child_sessions_tool" not in created["toolPolicy"]["allowedTools"]
    assert "agent_message_tool" in created["toolPolicy"]["allowedTools"]
    assert "agent_tool_permission_request_tool" in created["toolPolicy"]["allowedTools"]
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])


def test_agent_create_api_allows_work_session_with_explicit_no_tools_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "纯聊天会话",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
            "toolPolicy": {
                "allowedTools": [],
                "preferredTools": [],
                "blockedTools": [],
            },
        },
    )

    assert response.status_code == 201, response.text
    agent = response.json()
    assert agent["toolPolicyId"].startswith("tool-")
    assert agent["toolPolicy"]["allowedTools"] == []
    assert agent["toolPolicy"]["preferredTools"] == []
    assert agent["toolPolicy"]["blockedTools"] == []
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])


def test_repair_adds_session_default_tools_to_legacy_work_session_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Legacy Session Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = agent_directory_service.load_state()
    raw_agent = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw_agent["toolPolicyId"] = agent_directory_service.DEFAULT_TOOL_POLICY_ID
    state["toolPolicies"][agent_directory_service.DEFAULT_TOOL_POLICY_ID] = agent_directory_service.default_tool_policy()
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == agent["agentId"])
    policy = repaired["toolPolicies"][repaired_agent["toolPolicyId"]]

    assert repaired_agent["toolPolicyId"].startswith("tool-")
    assert policy["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert policy["preferredTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    assert "read_file_tool" not in policy["allowedTools"]
    assert "grep_search_tool" in policy["allowedTools"]
    assert "glob_tool" in policy["allowedTools"]
    assert "cli_tool" in policy["allowedTools"]
    assert "cli_agent_run_tool" not in policy["allowedTools"]
    assert "search_memory_tool" not in policy["allowedTools"]
    assert "search_error_archive_tool" not in policy["allowedTools"]
    assert "record_learning_tool" not in policy["allowedTools"]
    assert "code_symbol_tool" in policy["allowedTools"]
    assert "create_child_session_tool" not in policy["allowedTools"]
    assert "list_child_sessions_tool" not in policy["allowedTools"]
    assert "agent_message_tool" in policy["allowedTools"]
    assert "agent_tool_permission_request_tool" in policy["allowedTools"]
    assert repaired_agent["metadata"]["onboardingStatus"] == "complete"


def test_repair_preserves_session_agent_explicit_tool_overrides(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Custom Session Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = agent_directory_service.load_state()
    raw_agent = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw_agent["toolPolicyId"] = f"tool-{agent['agentId']}"
    state["toolPolicies"][raw_agent["toolPolicyId"]] = {
        **agent_directory_service.default_tool_policy(raw_agent["toolPolicyId"]),
        "allowedTools": ["read_file_tool"],
        "preferredTools": ["read_file_tool"],
        "blockedTools": ["get_core_context_tool"],
    }
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == agent["agentId"])
    policy = repaired["toolPolicies"][repaired_agent["toolPolicyId"]]

    assert repaired_agent["toolPolicyId"] == f"tool-{agent['agentId']}"
    assert policy["allowedTools"] == []
    assert policy["preferredTools"] == []
    assert policy["blockedTools"] == ["get_core_context_tool"]
    assert "conversation_log_inspect_tool" not in policy["allowedTools"]
    assert "get_core_context_tool" not in policy["allowedTools"]


def test_repair_adds_explicit_no_tools_policy_to_fixed_evolution_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="Legacy Supervised Baseline",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="supervised_evolution",
        role_key="baseline",
        prompt_template_id="prompt-supervised-baseline",
        metadata={"fixedRole": True, "supervisedRole": "baseline"},
    )
    state = agent_directory_service.load_state()
    raw_agent = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw_agent["toolPolicyId"] = agent_directory_service.DEFAULT_TOOL_POLICY_ID
    state["toolPolicies"][agent_directory_service.DEFAULT_TOOL_POLICY_ID] = agent_directory_service.default_tool_policy()
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == agent["agentId"])
    policy = repaired["toolPolicies"][repaired_agent["toolPolicyId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])

    assert repaired_agent["toolPolicyId"] == f"tool-{agent['agentId']}"
    assert policy["allowedTools"] == []
    assert policy["networkAccess"] == "none"
    assert policy["mutationAccess"] == "none"
    assert not any(item["code"] == "default_empty_tool_policy_for_fixed_role" for item in workspace_agent["health"])


def test_repair_tightens_ai_search_source_role_tool_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="Signal Quality Gate",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="research",
        role_key="signal_quality_gate",
        prompt_template_id="prompt-chat-default",
        metadata={"fixedRole": True},
    )
    state = agent_directory_service.load_state()
    raw_agent = next(item for item in state["agents"] if item["agentId"] == agent["agentId"])
    raw_agent["toolPolicyId"] = f"tool-{agent['agentId']}"
    state["toolPolicies"][raw_agent["toolPolicyId"]] = agent_directory_service.default_session_agent_tool_policy(raw_agent["toolPolicyId"])
    agent_directory_service.save_state(state)

    repaired = agent_directory_service.repair_agent_directory()
    repaired_agent = next(item for item in repaired["agents"] if item["agentId"] == agent["agentId"])
    policy = repaired["toolPolicies"][repaired_agent["toolPolicyId"]]
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])

    assert policy["allowedTools"] == list(agent_directory_service.RESEARCH_SOURCE_ALLOWED_TOOLS)
    assert "apply_patch_tool" not in policy["allowedTools"]
    assert "cli_tool" not in policy["allowedTools"]
    assert "write_file_tool" not in policy["allowedTools"]
    assert policy["networkAccess"] == "controlled"
    assert policy["mutationAccess"] == "none"
    assert not any(item["code"] == "research_source_tool_policy_too_broad" for item in workspace_agent["health"])


def test_agent_create_api_rejects_incomplete_onboarding_payload(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)

    response = client.post(
        "/api/agents",
        json={
            "displayName": "半成品 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "research",
            "promptTemplateId": "prompt-research-broad",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Agent 创建信息不完整" in detail
    assert "角色键" in detail
    assert "人物档案" in detail
    assert "任务档案" in detail
    assert "工具包" in detail


def test_agent_create_api_rejects_blank_display_name(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    response = client.post("/api/agents", json={"displayName": "   ", "llmBindings": {"dialogue": {"modelId": "model-primary"}}})

    assert response.status_code == 422
    assert "功能名" in response.json()["detail"]


def test_agent_onboarding_health_clears_after_required_profiles_and_tools(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="完整 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        primary_mode="research",
        role_key="research_full",
        prompt_template_id="prompt-research-broad",
    )

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"communicationStyle": "先给结论，再列证据。"},
            "taskProfile": {"mission": "负责研究复核。", "taskTypes": ["research_review"]},
            "toolPolicy": {
                "allowedTools": ["agent_message_tool"],
                "preferredTools": ["agent_message_tool"],
                "writeScopes": ["private"],
            },
        },
    )

    assert response.status_code == 200, response.text
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    created = next(item for item in workspace["agents"] if item["agentId"] == agent["agentId"])
    assert created["metadata"]["onboardingStatus"] == "complete"
    assert created["metadata"]["onboardingMissing"] == []
    assert not any(item["code"] == "agent_onboarding_incomplete" for item in created["health"])
