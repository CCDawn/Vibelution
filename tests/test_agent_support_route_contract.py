"""A6 contract: remaining agent support JSON routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_support_models import (
    AgentChatRoomMembershipResponse,
    AgentMessageCreateResponse,
    AgentProjectMemoryUpdateResponse,
    AgentToolPolicyConfigurationListResponse,
    AgentToolPolicyConfigurationResponse,
    PromptTemplateResponse,
    PromptTemplateWorkspaceResponse,
)
from core.web.routes.agent_workbench_models import (
    AgentModeMembershipResponse,
    AgentToolGovernanceRequestResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_project_memory_update_list",
    "agent_tool_governance_request_list",
    "agent_tool_policy_configuration_list",
    "agent_tool_policy_configuration_detail",
    "agent_tool_policy_configuration_validate",
    "agent_tool_policy_configuration_update",
    "agent_project_memory_update_create",
    "agent_project_memory_update_resolve",
    "agent_message_create",
    "agent_chat_room_membership_update",
    "prompt_template_list",
    "prompt_template_detail",
    "prompt_template_update",
    "prompt_template_reset",
    "mode_binding_detail",
    "mode_binding_update",
    "mode_binding_slot_update",
    "mode_binding_pool_update",
}


def _is_router_decorator(decorator: ast.Call) -> bool:
    function = decorator.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id.lower().endswith("router")
    )


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(AGENTS_ROUTE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _is_router_decorator(decorator):
                found[node.name] = decorator
    return found


def test_agent_support_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(JSON_ROUTE_FUNCTIONS):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_model = any(
            keyword.arg == "response_model"
            and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
            for keyword in decorator.keywords
        )
        if not has_response_model:
            missing.append(name)
    assert missing == [], f"agent support routes must declare response_model: {missing}"


def test_agent_support_response_models_keep_unknown_fields(monkeypatch) -> None:
    proposal = AgentProjectMemoryUpdateResponse.model_validate(
        {"proposalId": "prop-1", "customProposal": True}
    )
    assert proposal.model_dump(exclude_unset=True)["customProposal"] is True

    policy = AgentToolPolicyConfigurationResponse.model_validate(
        {"agentId": "agent-live", "customPolicy": True}
    )
    assert policy.model_dump(exclude_unset=True)["customPolicy"] is True

    policy_list = AgentToolPolicyConfigurationListResponse.model_validate({"customList": True})
    assert policy_list.model_dump(exclude_unset=True)["customList"] is True

    created = AgentMessageCreateResponse.model_validate({"eventId": "evt-1", "customMessage": True})
    assert created.model_dump(exclude_unset=True)["customMessage"] is True

    rooms = AgentChatRoomMembershipResponse.model_validate({"customRooms": True})
    assert rooms.model_dump(exclude_unset=True)["customRooms"] is True

    workspace = PromptTemplateWorkspaceResponse.model_validate(
        {"templates": [{"promptTemplateId": "tpl-1", "customTemplate": True}], "customWorkspace": True}
    )
    workspace_dump = workspace.model_dump(exclude_unset=True)
    assert workspace_dump["customWorkspace"] is True
    assert workspace_dump["templates"][0]["customTemplate"] is True

    template = PromptTemplateResponse.model_validate(
        {"promptTemplateId": "tpl-1", "customTemplate": True}
    )
    assert template.model_dump(exclude_unset=True)["customTemplate"] is True

    bindings = AgentModeMembershipResponse.model_validate(
        {"schemaVersion": 1, "customBindings": True}
    )
    assert bindings.model_dump(exclude_unset=True)["customBindings"] is True

    governance = AgentToolGovernanceRequestResponse.model_validate(
        {"requestId": "req-1", "customGovernance": True}
    )
    assert governance.model_dump(exclude_unset=True)["customGovernance"] is True

    monkeypatch.setattr(agent_routes, "_ensure_config_agent_instances", lambda: None)
    monkeypatch.setattr(agent_routes, "invalidate_agent_config_workspace_cache", lambda: None)

    expected_proposals = [{"proposalId": "prop-1", "customProposal": True}]
    monkeypatch.setattr(
        agent_routes,
        "list_project_memory_update_proposals",
        lambda *_args, **_kwargs: expected_proposals,
    )
    listed = client.get("/api/agents/project-memory-updates?status=pending&limit=8")
    assert listed.status_code == 200
    assert listed.json() == expected_proposals

    expected_created = {"proposalId": "prop-1", "customCreated": True}
    monkeypatch.setattr(
        agent_routes,
        "write_project_memory_update_proposal",
        lambda *_args, **_kwargs: expected_created,
    )
    created_response = client.post(
        "/api/agents/agent-live/project-memory-updates",
        json={"laneId": "lane-1", "focus": "focus", "update": "update"},
    )
    assert created_response.status_code == 201
    assert created_response.json() == expected_created

    expected_resolved = {"proposalId": "prop-1", "status": "applied", "customResolved": True}
    monkeypatch.setattr(
        agent_routes,
        "resolve_project_memory_update_proposal",
        lambda *_args, **_kwargs: expected_resolved,
    )
    resolved = client.patch(
        "/api/agents/agent-live/project-memory-updates/prop-1",
        json={"status": "applied", "resolvedBy": "user", "resolutionNote": "ok"},
    )
    assert resolved.status_code == 200
    assert resolved.json() == expected_resolved

    expected_governance = [{"requestId": "req-1", "customGovernance": True}]
    monkeypatch.setattr(
        agent_routes.agent_tool_governance_service,
        "list_tool_governance_requests",
        lambda *_args, **_kwargs: expected_governance,
    )
    governance_list = client.get("/api/agents/tool-governance-requests?status=pending_review")
    assert governance_list.status_code == 200
    assert governance_list.json() == expected_governance

    expected_policy_list = {"items": [{"agentId": "agent-live", "customItem": True}], "customList": True}
    monkeypatch.setattr(
        agent_routes.tool_policy_configuration_service,
        "list_tool_policy_configurations",
        lambda *_args, **_kwargs: expected_policy_list,
    )
    policy_listed = client.get("/api/agents/tool-policies/configurations")
    assert policy_listed.status_code == 200
    assert policy_listed.json() == expected_policy_list

    expected_policy = {"agentId": "agent-live", "customPolicy": True}
    monkeypatch.setattr(
        agent_routes.tool_policy_configuration_service,
        "get_tool_policy_configuration",
        lambda *_args, **_kwargs: expected_policy,
    )
    monkeypatch.setattr(
        agent_routes.tool_policy_configuration_service,
        "validate_tool_policy_configuration",
        lambda *_args, **_kwargs: expected_policy,
    )
    monkeypatch.setattr(
        agent_routes.tool_policy_configuration_service,
        "update_tool_policy_configuration",
        lambda *_args, **_kwargs: expected_policy,
    )
    detail = client.get("/api/agents/agent-live/tool-policy")
    assert detail.status_code == 200
    assert detail.json() == expected_policy
    validated = client.post("/api/agents/agent-live/tool-policy/validate", json={"toolPolicy": {}})
    assert validated.status_code == 200
    assert validated.json() == expected_policy
    updated = client.put(
        "/api/agents/agent-live/tool-policy",
        json={
            "toolPolicy": {},
            "expectedAgentUpdatedAt": "t1",
            "expectedPolicyFingerprint": "fp1",
            "confirmed": True,
        },
    )
    assert updated.status_code == 200
    assert updated.json() == expected_policy

    expected_workspace = {"templates": [{"promptTemplateId": "tpl-1", "customTemplate": True}], "customWorkspace": True}
    monkeypatch.setattr(agent_routes, "list_prompt_templates", lambda *_args, **_kwargs: expected_workspace)
    workspace_response = client.get("/api/prompt-templates?includeInactive=true")
    assert workspace_response.status_code == 200
    assert workspace_response.json() == expected_workspace

    expected_template = {"promptTemplateId": "tpl-1", "customTemplate": True}
    monkeypatch.setattr(agent_routes, "get_prompt_template", lambda *_args, **_kwargs: expected_template)
    monkeypatch.setattr(agent_routes, "update_prompt_template", lambda *_args, **_kwargs: expected_template)
    monkeypatch.setattr(agent_routes, "reset_prompt_template", lambda *_args, **_kwargs: expected_template)
    template_detail = client.get("/api/prompt-templates/tpl-1")
    assert template_detail.status_code == 200
    assert template_detail.json() == expected_template
    template_update = client.patch("/api/prompt-templates/tpl-1", json={"name": "Live"})
    assert template_update.status_code == 200
    assert template_update.json() == expected_template
    template_reset = client.post("/api/prompt-templates/tpl-1/reset")
    assert template_reset.status_code == 200
    assert template_reset.json() == expected_template

    expected_bindings = {"schemaVersion": 1, "modes": {"chat": {"customMode": True}}, "customBindings": True}
    monkeypatch.setattr(agent_routes, "get_mode_bindings_payload", lambda *_args, **_kwargs: expected_bindings)
    monkeypatch.setattr(agent_routes, "update_mode_binding", lambda *_args, **_kwargs: expected_bindings)
    bindings = client.get("/api/agent-mode-bindings")
    assert bindings.status_code == 200
    assert bindings.json() == expected_bindings
    mode_update = client.patch("/api/agent-mode-bindings/chat", json={"defaultAgentId": "agent-live"})
    assert mode_update.status_code == 200
    assert mode_update.json() == expected_bindings
    slot_update = client.patch("/api/agent-mode-bindings/supervised_evolution/slots/executor", json={"agentId": "agent-live"})
    assert slot_update.status_code == 200
    assert slot_update.json() == expected_bindings
    pool_update = client.patch("/api/agent-mode-bindings/research/pool", json={"agentIds": ["agent-live"]})
    assert pool_update.status_code == 200
    assert pool_update.json() == expected_bindings

    expected_rooms = {"roomIds": ["room-1"], "customRooms": True}
    monkeypatch.setattr(
        agent_routes,
        "update_agent_chat_room_membership",
        lambda *_args, **_kwargs: expected_rooms,
    )
    rooms_response = client.patch("/api/agents/agent-live/chat-rooms", json={"roomIds": ["room-1"]})
    assert rooms_response.status_code == 200
    assert rooms_response.json() == expected_rooms
