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

def test_agent_reset_api_clears_runtime_state_without_removing_bindings_or_memory(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reset_events = []
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    direct_session = session_service.create_chat_session(title="Resettable Agent")
    agent = agent_directory_service.get_agent(direct_session["agentId"])
    peer = agent_directory_service.create_agent_instance(
        display_name="Peer Agent",
        direct_session_id="session-peer-agent",
    )
    agent_mode_binding_service.update_mode_binding(
        "chat",
        default_agent_id=agent["agentId"],
        available_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    room = chat_room_service.create_chat_room(
        title="调试群聊",
        participant_agent_ids=[agent["agentId"], peer["agentId"]],
    )
    team = team_service.create_team(
        name="调试团队",
        members=[{"agentId": agent["agentId"], "role": "lead"}],
    )
    workspace_path = tmp_path / agent["workspacePath"]
    for subdir in ("inbox", "events", "logs", "runs", "scratch", "artifacts"):
        target = workspace_path / subdir
        target.mkdir(parents=True, exist_ok=True)
        (target / "trace.txt").write_text("runtime trace", encoding="utf-8")
    memory_file = workspace_path / "memory" / "keep.md"
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    memory_file.write_text("private memory", encoding="utf-8")

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["agent"]["agentId"] == agent["agentId"]
    assert payload["agent"]["status"] == "active"
    assert payload["agent"]["directSessionId"] != direct_session["id"]
    assert payload["resetSummary"]["clearedRuntimeState"] is True
    assert payload["resetSummary"]["resetDirectSession"] is True
    assert payload["resetSummary"]["previousDirectSessionId"] == direct_session["id"]
    assert payload["resetSummary"]["replacementDirectSessionId"] == payload["agent"]["directSessionId"]
    assert payload["agent"]["metadata"]["directSessionVisibility"] == agent_directory_service.SESSION_AGENT_VISIBILITY_ACTIVE
    assert "team_membership" in payload["resetSummary"]["preserved"]
    for subdir in ("inbox", "events", "logs", "runs", "scratch", "artifacts"):
        assert (workspace_path / subdir).is_dir()
        assert not (workspace_path / subdir / "trace.txt").exists()
    assert memory_file.read_text(encoding="utf-8") == "private memory"
    session_ids = {item["id"] for item in session_service.list_sessions()}
    assert direct_session["id"] not in session_ids
    assert payload["agent"]["directSessionId"] in session_ids
    active_session = session_service.get_active_session_detail()
    assert active_session["id"] == payload["agent"]["directSessionId"]
    bindings = agent_mode_binding_service.get_mode_bindings_payload()["modes"]
    assert bindings["chat"]["defaultAgentId"] == agent["agentId"]
    assert agent["agentId"] in bindings["chat"]["availableAgentIds"]
    room_detail = chat_room_service.get_chat_room_detail(room["roomId"])
    assert agent["agentId"] in {participant["agentId"] for participant in room_detail["participants"]}
    team_detail = team_service.get_team(team["teamId"])
    assert agent["agentId"] in [member["agentId"] for member in team_detail["members"]]
    event_codes = [item[0][2] for item in reset_events]
    assert event_codes.count("agent.reset.requested") == 1
    assert event_codes.count("agent.reset.completed") == 1
    requested_fields = next(item[1]["fields"] for item in reset_events if item[0][2] == "agent.reset.requested")
    completed_fields = next(item[1]["fields"] for item in reset_events if item[0][2] == "agent.reset.completed")
    assert requested_fields["agentId"] == agent["agentId"]
    assert requested_fields["clearRuntimeState"] is True
    assert requested_fields["resetDirectSession"] is True
    assert completed_fields["agentId"] == agent["agentId"]
    assert completed_fields["deletedPathCount"] == len(payload["resetSummary"]["deletedPaths"])
    assert completed_fields["deletedPathCount"] >= 6


def test_agent_reset_api_can_keep_existing_direct_session_when_requested(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    direct_session = session_service.create_chat_session(title="保留直连会话")
    agent = agent_directory_service.get_agent(direct_session["agentId"])

    response = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={"resetDirectSession": False},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resetSummary"]["resetDirectSession"] is False
    assert payload["agent"]["directSessionId"] == direct_session["id"]
    assert direct_session["id"] in {item["id"] for item in session_service.list_sessions()}


def test_agent_reset_api_can_reset_session_agent_advanced_policies_without_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Advanced Reset Agent")
    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"gender": "female", "age": "34", "communicationStyle": "brief"},
            "taskProfile": {"mission": "run experiments", "taskTypes": ["research"]},
            "toolPolicy": {
                "policyId": agent["toolPolicyId"],
                "allowedTools": ["web_search"],
                "preferredTools": ["web_search"],
                "blockedTools": [],
                "readScopes": ["private"],
                "writeScopes": ["private", "shared"],
            },
            "memoryPolicy": {
                "policyId": agent["memoryPolicyId"],
                "readSharedGroups": ["research"],
                "writeSharedGroups": ["research"],
            },
            "delegationPolicy": {"allowSubagents": True, "maxConcurrent": 3, "maxDepth": 2},
            "supervisionPolicy": {"supervisionEnabled": True, "requiresReview": True, "reviewMode": "approval"},
        },
    )
    assert response.status_code == 200, response.text

    reset = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={
            "clearRuntimeState": False,
            "resetPersonaProfile": True,
            "resetTaskProfile": True,
            "resetToolPolicy": True,
            "resetMemoryPolicy": True,
            "resetRuntimePolicy": True,
        },
    )

    assert reset.status_code == 200, reset.text
    payload = reset.json()
    assert payload["resetSummary"]["clearedRuntimeState"] is False
    assert payload["agent"]["personaProfile"] == {}
    assert payload["agent"]["taskProfile"] == {}
    assert payload["resetSummary"]["resetPersonaProfile"] is False
    assert payload["resetSummary"]["resetTaskProfile"] is False
    assert payload["agent"]["toolPolicyId"].startswith("tool-")
    assert payload["agent"]["toolPolicy"]["allowedTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert payload["agent"]["toolPolicy"]["preferredTools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    assert "read_file_tool" not in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "cli_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "apply_patch_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "run_test_for_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "create_child_session_tool" not in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "list_child_sessions_tool" not in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "agent_message_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert "agent_tool_permission_request_tool" in payload["agent"]["toolPolicy"]["allowedTools"]
    assert payload["agent"]["memoryPolicy"]["readSharedGroups"] == []
    assert payload["agent"]["memoryPolicy"]["writeSharedGroups"] == []
    assert payload["agent"]["metadata"]["delegationPolicy"]["allowSubagents"] is False
    assert payload["agent"]["metadata"]["supervisionPolicy"]["supervisionEnabled"] is False


def test_agent_reset_api_can_reset_team_agent_profiles(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="Advanced Profile Reset Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )
    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "personaProfile": {"gender": "female", "age": "34", "communicationStyle": "brief"},
            "taskProfile": {"mission": "run experiments", "taskTypes": ["research"]},
        },
    )
    assert response.status_code == 200, response.text

    reset = client.post(
        f"/api/agents/{agent['agentId']}/reset",
        json={
            "clearRuntimeState": False,
            "resetPersonaProfile": True,
            "resetTaskProfile": True,
            "resetToolPolicy": False,
            "resetMemoryPolicy": False,
            "resetRuntimePolicy": False,
        },
    )

    assert reset.status_code == 200, reset.text
    payload = reset.json()
    assert payload["resetSummary"]["resetPersonaProfile"] is True
    assert payload["resetSummary"]["resetTaskProfile"] is True
    assert payload["agent"]["personaProfile"]["communicationStyle"] == ""
    assert payload["agent"]["personaProfile"]["age"] == ""
    assert payload["agent"]["taskProfile"]["mission"] == ""
    assert payload["agent"]["taskProfile"]["taskTypes"] == []


def test_agent_reset_api_rejects_archived_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    reset_events = []
    monkeypatch.setattr(
        agents_route,
        "record_runtime_scene_event",
        lambda *args, **kwargs: reset_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = session_service.create_chat_session(title="Archived Reset Agent")
    agent_directory_service.archive_agent_instance(agent["agentId"])

    response = client.post(f"/api/agents/{agent['agentId']}/reset", json={})

    assert response.status_code == 422
    assert "Archived Agent cannot be reset" in response.json()["detail"]
    assert agent_directory_service.get_agent(agent["agentId"], include_archived=True)["status"] == "archived"
    event_codes = [item[0][2] for item in reset_events]
    assert event_codes == ["agent.reset.requested", "agent.reset.failed"]
    failed_fields = reset_events[-1][1]["fields"]
    assert failed_fields["agentId"] == agent["agentId"]
    assert failed_fields["errorType"] == "AgentDirectoryError"


def test_agent_inbox_consume_all_api_clears_pending_health_issue(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    target = agent_directory_service.create_agent_instance(display_name="收件 Agent")
    source = agent_directory_service.create_agent_instance(display_name="来源 Agent")
    for index in range(3):
        agent_directory_service.write_agent_inbox_message(
            target["agentId"],
            content=f"消息 {index}",
            source_agent_id=source["agentId"],
        )

    before = agent_config_workspace_service.get_agent_config_workspace()
    assert any(
        item["code"] == "pending_inbox_messages"
        for item in before["health"]["byAgent"][target["agentId"]]
    )

    response = client.post(
        f"/api/agents/{target['agentId']}/messages/consume-all",
        json={"consumedBySessionId": target["directSessionId"], "consumedByTurnId": "test"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["consumedCount"] == 3
    assert payload["remainingPendingCount"] == 0
    assert agent_directory_service.count_agent_inbox_messages_for_agent(target["agentId"], status="pending") == 0
    after = agent_config_workspace_service.get_agent_config_workspace()
    assert all(
        item["code"] != "pending_inbox_messages"
        for item in after["health"]["byAgent"].get(target["agentId"], [])
    )


def test_agent_config_workspace_agent_patch_updates_card_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(
        display_name="旧 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        prompt_template_id="prompt-chat-default",
    )
    workspace = agent_config_workspace_service.get_agent_config_workspace()
    memory_policy_id = workspace["memoryPolicies"][0]["policyId"]

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "displayName": "新 Agent",
            "llmBindings": {"dialogue": {"modelId": "model-research"}},
            "promptTemplateId": "prompt-research-broad",
            "toolPolicyId": "default",
            "memoryPolicyId": memory_policy_id,
            "status": "active",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["displayName"] == "新 Agent"
    assert payload["llmBindings"]["dialogue"]["modelId"] == "model-research"
    assert "profileId" not in payload
    assert payload["promptTemplateId"] == "prompt-research-broad"
    assert payload["toolPolicyId"] == f"tool-{agent['agentId']}"
    assert payload["memoryPolicyId"] == memory_policy_id


def test_normalize_tool_policy_dedupes_tool_lists_preserving_order():
    policy = agent_directory_service.normalize_tool_policy(
        {
            "policyId": "tool-test",
            "allowedTools": ["cli_tool", "rg_tool", "cli_tool", "", "rg_tool"],
            "preferredTools": ["cli_tool", "cli_tool", "read_file_tool"],
            "blockedTools": ["danger", "danger"],
        },
        "tool-test",
    )

    assert policy["allowedTools"] == ["cli_tool", "rg_tool"]
    assert policy["preferredTools"] == ["cli_tool"]
    assert policy["blockedTools"] == ["danger"]


def test_agent_runtime_blocks_disabled_direct_read_tool_even_when_granted(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(display_name="Read Disabled Agent", primary_mode="chat")

    with agent_directory_service.active_agent_runtime(
        agent["agentId"],
        runtime_tool_grants=["read_file_tool", "cli_tool"],
        runtime_tool_source="test",
    ):
        policy = agent_directory_service.current_agent_runtime()["toolPolicy"]
        decision = agent_directory_service.evaluate_current_tool_policy("read_file_tool", {"file_path": "demo.py"})

    assert "read_file_tool" not in policy["allowedTools"]
    assert "cli_tool" in policy["allowedTools"]
    assert decision.allowed is False
    assert decision.reason == "direct_read_tool_disabled"


def test_session_agent_policy_id_patch_honors_selected_shared_policy_without_forcing_defaults(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    agent = agent_directory_service.create_agent_instance(
        display_name="会话工具 Agent",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    state = agent_directory_service.load_state()
    state["toolPolicies"]["tool-shared-minimal"] = {
        **agent_directory_service.default_tool_policy("tool-shared-minimal"),
        "allowedTools": ["agent_message_tool"],
        "preferredTools": ["agent_message_tool"],
    }
    agent_directory_service.save_state(state)

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={"toolPolicyId": "tool-shared-minimal"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["toolPolicyId"] == "tool-shared-minimal"
    assert payload["toolPolicy"]["allowedTools"] == ["agent_message_tool"]
    assert payload["toolPolicy"]["preferredTools"] == ["agent_message_tool"]
    assert "conversation_log_inspect_tool" not in payload["toolPolicy"]["allowedTools"]
    assert "cli_agent_run_tool" not in payload["toolPolicy"]["allowedTools"]
    persisted = agent_directory_service.load_state()
    assert persisted["toolPolicies"]["tool-shared-minimal"]["allowedTools"] == ["agent_message_tool"]


def test_agent_api_explains_session_tool_policy_sources(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    default_agent = agent_directory_service.create_agent_instance(
        display_name="默认会话 Agent",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    empty_agent = agent_directory_service.create_agent_instance(
        display_name="空工具 Agent",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    empty_agent = agent_directory_service.update_agent_instance(
        empty_agent["agentId"],
        tool_policy={"allowedTools": [], "preferredTools": []},
    )
    wide_agent = agent_directory_service.create_agent_instance(
        display_name="宽权限 Agent",
        primary_mode="chat",
        prompt_template_id="prompt-chat-default",
    )
    wide_agent = agent_directory_service.update_agent_instance(
        wide_agent["agentId"],
        tool_policy={
            "allowedTools": [
                *agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS,
                "web_search_tool",
            ],
            "preferredTools": ["cli_tool", "web_search_tool"],
        },
    )

    default_payload = agent_directory_service.get_agent(default_agent["agentId"])
    empty_payload = agent_directory_service.get_agent(empty_agent["agentId"])
    wide_payload = agent_directory_service.get_agent(wide_agent["agentId"])

    assert default_payload["toolPolicySource"]["kind"] == "session_default_private"
    assert empty_payload["toolPolicySource"]["kind"] == "agent_private_override"
    assert empty_payload["toolPolicySource"]["allowedToolCount"] == 0
    assert wide_payload["toolPolicySource"]["kind"] == "legacy_wide_private_override"
    assert wide_payload["toolPolicySource"]["isLegacyWide"] is True
    assert set(wide_payload["toolPolicySource"]["mutatingTools"]) == (
        set(agent_directory_service.MUTATING_AGENT_TOOL_NAMES) - agent_directory_service.SUBAGENT_DELEGATION_TOOL_NAMES
    )


def test_agent_api_rejects_legacy_profile_and_template_fields(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)

    create_response = client.post(
        "/api/agents",
        json={
            "displayName": "旧字段 Agent",
            "profileId": "primary",
            "llmBindings": {"dialogue": {"modelId": "model-primary"}},
            "primaryMode": "chat",
            "promptTemplateId": "prompt-chat-default",
            "toolPolicy": {"allowedTools": ["agent_message_tool"]},
        },
    )

    assert create_response.status_code == 422
    assert "profileId" in create_response.text

    agent = agent_directory_service.create_agent_instance(
        display_name="新字段 Agent",
        llm_bindings={"dialogue": {"modelId": "model-primary"}},
        prompt_template_id="prompt-chat-default",
    )
    patch_response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={"templateId": "primary", "promptTemplateId": "prompt-chat-default"},
    )

    assert patch_response.status_code == 422
    assert "templateId" in patch_response.text


def test_agent_patch_rejects_unknown_policy_ids_and_protected_archive(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    agent = agent_directory_service.create_agent_instance(display_name="核心 Agent", metadata={"protected": True})

    missing_policy = client.patch(f"/api/agents/{agent['agentId']}", json={"toolPolicyId": "missing-policy"})
    archive = client.patch(f"/api/agents/{agent['agentId']}", json={"status": "archived"})

    assert missing_policy.status_code == 422
    assert "Unknown ToolPolicy" in missing_policy.json()["detail"]
    assert archive.status_code == 422
    assert "Protected core Agent" in archive.json()["detail"]


def test_agent_patch_tool_policy_creates_agent_private_policy_and_logs(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    recorded_events = []
    monkeypatch.setattr(
        agent_directory_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    agent = agent_directory_service.create_agent_instance(display_name="工具 Agent")

    response = client.patch(
        f"/api/agents/{agent['agentId']}",
        json={
            "toolPolicy": {
                "allowedTools": ["image2_generate_tool"],
                "blockedTools": ["shell_command"],
                "writeScopes": ["shared", "external", "shared"],
                "readScopes": ["shared", "private", "external"],
            }
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["toolPolicyId"] == f"tool-{agent['agentId']}"
    assert payload["toolPolicy"]["allowedTools"] == ["image2_generate_tool"]
    assert payload["toolPolicy"]["blockedTools"] == ["shell_command"]
    assert payload["toolPolicy"]["writeScopes"] == ["shared"]
    assert payload["toolPolicy"]["readScopes"] == ["shared", "private"]
    assert any(
        event[0][:3] == ("agent_directory", "tool_policy", "agent.tool_policy.updated")
        and event[1]["fields"]["allowedToolCount"] == 1
        and event[1]["fields"]["blockedToolCount"] == 1
        and event[1]["fields"]["sharedWriteEnabled"] is True
        for event in recorded_events
    )
