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

def test_agent_tool_governance_low_risk_change_auto_applies_for_governance_agent(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    recorded_events = []
    monkeypatch.setattr(
        agent_tool_governance_service,
        "record_runtime_scene_event",
        lambda *args, **kwargs: recorded_events.append((args, kwargs)) or {"accepted": True},
    )
    advisor = agent_directory_service.create_agent_instance(
        display_name="能力顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="资料 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["read_file_tool", "grep_search_tool"],
        reason="资料 Agent 需要只读检索项目材料。",
        apply_mode="auto",
    )

    updated = agent_directory_service.get_agent(target["agentId"])
    assert request["status"] == "applied"
    assert request["requiresApproval"] is False
    assert request["riskLevel"] == "low"
    assert updated["toolPolicy"]["allowedTools"] == ["read_file_tool", "grep_search_tool"]
    assert request["after"]["allowedTools"] == ["read_file_tool", "grep_search_tool"]
    assert any(
        event[0][:3] == ("agent_tool_governance", "tool_policy", "agent_tool_governance.request_applied")
        and event[1]["fields"]["targetAgentId"] == target["agentId"]
        for event in recorded_events
    )
    assert agent_tool_governance_service.list_tool_governance_requests(agent_id=target["agentId"], status="applied")[0][
        "requestId"
    ] == request["requestId"]


def test_agent_tool_governance_high_risk_change_waits_for_review_and_can_be_approved(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    advisor = agent_directory_service.create_agent_instance(
        display_name="权限顾问",
        metadata={"systemRole": "capability_steward", "researchOrgRole": "capability_steward"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="执行 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["cli_tool"],
        reason="执行 Agent 需要运行验证命令。",
        apply_mode="auto",
    )
    unchanged = agent_directory_service.get_agent(target["agentId"])

    assert request["status"] == "pending_review"
    assert request["requiresApproval"] is True
    assert request["riskLevel"] == "high"
    assert unchanged["toolPolicy"]["allowedTools"] == []

    approved = agent_tool_governance_service.resolve_tool_governance_request(
        target["agentId"],
        request["requestId"],
        decision="approve",
        resolved_by="user",
        resolution_note="允许本轮验证。",
    )
    updated = agent_directory_service.get_agent(target["agentId"])

    assert approved["status"] == "applied"
    assert approved["resolvedBy"] == "user"
    assert updated["toolPolicy"]["allowedTools"] == ["cli_tool"]


def test_agent_tool_governance_session_scope_approval_does_not_persist_policy(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    target = agent_directory_service.create_agent_instance(
        display_name="临时授权 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=target["agentId"],
        grant_tools=["cli_tool"],
        reason="当前会话需要运行一次验证命令。",
        apply_mode="auto",
        grant_scope="session",
        source_session_id="session-tool-approval",
        source_turn_id="turn-request",
    )
    unchanged = agent_directory_service.get_agent(target["agentId"])

    assert request["status"] == "pending_review"
    assert request["grantScope"] == "session"
    assert unchanged["toolPolicy"]["allowedTools"] == []

    approved = agent_tool_governance_service.resolve_tool_governance_request(
        target["agentId"],
        request["requestId"],
        decision="approve",
        resolved_by="user",
        resolution_note="允许当前会话临时使用。",
    )
    still_persistent = agent_directory_service.get_agent(target["agentId"])
    base_policy = agent_directory_service.resolve_tool_policy_for_agent(target["agentId"])
    session_policy = agent_directory_service.resolve_tool_policy_for_agent(
        target["agentId"],
        session_id="session-tool-approval",
        turn_id="turn-next",
    )
    other_session_policy = agent_directory_service.resolve_tool_policy_for_agent(
        target["agentId"],
        session_id="session-other",
    )

    assert approved["status"] == "applied"
    assert approved["grantScope"] == "session"
    assert approved["appliedToolPolicyId"] == ""
    assert approved["temporaryGrant"]["grantTools"] == ["cli_tool"]
    assert still_persistent["toolPolicy"]["allowedTools"] == []
    assert base_policy["allowedTools"] == []
    assert session_policy["allowedTools"] == ["cli_tool"]
    assert session_policy["temporaryAllowedTools"] == ["cli_tool"]
    assert other_session_policy["allowedTools"] == []


def test_session_detail_surfaces_pending_tool_governance_request(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    session = session_service.create_chat_session(title="审批会话")
    agent_id = session["agentId"]
    request = agent_tool_governance_service.submit_tool_governance_request(
        agent_id,
        proposed_by_agent_id=agent_id,
        grant_tools=["read_file_tool"],
        reason="需要当前会话临时读取文件。",
        apply_mode="auto",
        grant_scope="session",
        source_session_id=session["id"],
        source_turn_id="turn-request",
    )

    detail = session_service.get_session_detail(session["id"])

    assert detail["pendingToolGovernanceRequests"][0]["requestId"] == request["requestId"]
    assert detail["pendingToolGovernanceRequests"][0]["grantScope"] == "session"
    assert detail["pendingToolGovernanceRequests"][0]["policyDelta"]["grantTools"] == ["read_file_tool"]


def test_agent_tool_governance_uses_shared_tool_catalog_risk_metadata(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    advisor = agent_directory_service.create_agent_instance(
        display_name="工具目录顾问",
        metadata={"systemRole": "capability_steward", "researchOrgRole": "capability_steward"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="图像 Agent",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["image2_generate_tool"],
        reason="图像 Agent 需要生成研究配图。",
        apply_mode="auto",
    )

    assert request["status"] == "pending_review"
    assert request["riskLevel"] == "high"
    assert {"model_cost", "artifact_write"}.issubset(set(request["riskTags"]))
    assert agent_directory_service.get_agent(target["agentId"])["toolPolicy"]["allowedTools"] == []


def test_agent_tool_governance_routes_create_and_resolve_requests(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(agents_route, "_ensure_config_agent_instances", lambda: None)
    advisor = agent_directory_service.create_agent_instance(
        display_name="路由顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="路由目标",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )

    created = client.post(
        f"/api/agents/{target['agentId']}/tool-governance-requests",
        json={
            "proposedByAgentId": advisor["agentId"],
            "grantTools": ["image2_generate_tool"],
            "reason": "需要图片生成能力。",
            "applyMode": "auto",
        },
    )

    assert created.status_code == 201, created.text
    request = created.json()
    assert request["status"] == "pending_review"
    listed = client.get("/api/agents/tool-governance-requests", params={"agentId": target["agentId"]})
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["requestId"] == request["requestId"]

    resolved = client.patch(
        f"/api/agents/{target['agentId']}/tool-governance-requests/{request['requestId']}",
        json={"decision": "reject", "resolvedBy": "user", "resolutionNote": "暂不开放。"},
    )

    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "rejected"


def test_agent_config_workspace_surfaces_recent_tool_governance_requests(tmp_path, monkeypatch):
    _use_tmp_project_root(tmp_path, monkeypatch)
    monkeypatch.setattr(config_service, "get_config_workspace", _fake_config_workspace)
    advisor = agent_directory_service.create_agent_instance(
        display_name="配置顾问",
        metadata={"systemRole": "organization_advisor", "researchOrgRole": "organization_advisor"},
    )
    target = agent_directory_service.create_agent_instance(
        display_name="配置目标",
        primary_mode="research",
        role_key="research_broad",
        prompt_template_id="prompt-research-broad",
    )
    request = agent_tool_governance_service.submit_tool_governance_request(
        target["agentId"],
        proposed_by_agent_id=advisor["agentId"],
        grant_tools=["cli_tool"],
        reason="需要命令验证。",
    )

    workspace = agent_config_workspace_service.get_agent_config_workspace()
    workspace_agent = next(item for item in workspace["agents"] if item["agentId"] == target["agentId"])

    assert workspace_agent["toolGovernanceRequests"][0]["requestId"] == request["requestId"]
    assert workspace_agent["toolGovernanceRequests"][0]["status"] == "pending_review"
