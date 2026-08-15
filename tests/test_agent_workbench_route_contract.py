"""A5 contract: Agent Center workbench write routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_activity_models import AgentInboxMessageResponse
from core.web.routes.agent_catalog_models import AgentDocumentResponse
from core.web.routes.agent_workbench_models import (
    AgentAvatarUploadResponse,
    AgentInboxConsumeAllResponse,
    AgentModeMembershipResponse,
    AgentPurgeResponse,
    AgentToolGovernanceRequestResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_avatar_update",
    "agent_avatar_upload",
    "agent_tool_governance_request_create",
    "agent_tool_governance_request_resolve",
    "agent_message_consume",
    "agent_messages_consume_all",
    "agent_mode_membership_update",
    "agent_purge",
}


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


def _is_router_decorator(decorator: ast.Call) -> bool:
    function = decorator.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id.lower().endswith("router")
    )


def test_agent_workbench_routes_declare_response_model() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(JSON_ROUTE_FUNCTIONS):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_model = False
        for keyword in decorator.keywords:
            if keyword.arg != "response_model":
                continue
            if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
                continue
            has_response_model = True
        if not has_response_model:
            missing.append(name)
    assert missing == [], f"agent workbench write routes must declare response_model: {missing}"


def test_agent_workbench_response_models_keep_unknown_fields(monkeypatch) -> None:
    avatar = AgentDocumentResponse.model_validate(
        {"agentId": "agent-live", "customAvatar": True}
    )
    assert avatar.model_dump(exclude_unset=True)["customAvatar"] is True

    upload = AgentAvatarUploadResponse.model_validate(
        {
            "path": "avatars/live.png",
            "agent": {"agentId": "agent-live", "customAgent": True},
            "customUpload": True,
        }
    )
    upload_dump = upload.model_dump(exclude_unset=True)
    assert upload_dump["customUpload"] is True
    assert upload_dump["agent"]["customAgent"] is True

    governance = AgentToolGovernanceRequestResponse.model_validate(
        {"requestId": "req-1", "customGovernance": True}
    )
    assert governance.model_dump(exclude_unset=True)["customGovernance"] is True

    consumed = AgentInboxMessageResponse.model_validate(
        {"messageId": "msg-1", "customConsumed": True}
    )
    assert consumed.model_dump(exclude_unset=True)["customConsumed"] is True

    consume_all = AgentInboxConsumeAllResponse.model_validate(
        {"agentId": "agent-live", "consumedCount": 2, "customConsumeAll": True}
    )
    consume_all_dump = consume_all.model_dump(exclude_unset=True)
    assert consume_all_dump["consumedCount"] == 2
    assert consume_all_dump["customConsumeAll"] is True

    membership = AgentModeMembershipResponse.model_validate(
        {"schemaVersion": 1, "modes": {"chat": {"customMode": True}}, "customMembership": True}
    )
    membership_dump = membership.model_dump(exclude_unset=True)
    assert membership_dump["customMembership"] is True
    assert membership_dump["modes"]["chat"]["customMode"] is True

    purge = AgentPurgeResponse.model_validate(
        {
            "agentId": "agent-live",
            "purgeSummary": {"sessions": {"customSession": True}},
            "customPurge": True,
        }
    )
    purge_dump = purge.model_dump(exclude_unset=True)
    assert purge_dump["customPurge"] is True
    assert purge_dump["purgeSummary"]["sessions"]["customSession"] is True

    expected_avatar = {"agentId": "agent-live", "customAvatar": True}
    monkeypatch.setattr(agent_routes, "update_agent_avatar", lambda *_args, **_kwargs: expected_avatar)
    avatar_response = client.patch(
        "/api/agents/agent-live/avatar",
        json={"avatarImagePath": "avatars/live.png", "resetToDefault": False},
    )
    assert avatar_response.status_code == 200
    assert avatar_response.json() == expected_avatar

    expected_upload = {
        "path": "avatars/live.png",
        "url": "/api/agents/avatar-image/live.png",
        "agent": {"agentId": "agent-live", "customAgent": True},
        "customUpload": True,
    }
    monkeypatch.setattr(agent_routes, "store_agent_avatar_image", lambda *_args, **_kwargs: expected_upload)
    upload_response = client.post(
        "/api/agents/agent-live/avatar-image",
        json={"filename": "live.png", "contentType": "image/png", "dataBase64": "Zg=="},
    )
    assert upload_response.status_code == 200
    assert upload_response.json() == expected_upload

    expected_governance = {
        "requestId": "req-1",
        "status": "pending_review",
        "customGovernance": True,
    }
    monkeypatch.setattr(
        agent_routes.agent_tool_governance_service,
        "submit_tool_governance_request",
        lambda *_args, **_kwargs: expected_governance,
    )
    created = client.post(
        "/api/agents/agent-live/tool-governance-requests",
        json={"proposedByAgentId": "advisor", "reason": "need tools", "applyMode": "auto"},
    )
    assert created.status_code == 201
    assert created.json() == expected_governance

    expected_resolved = {
        "requestId": "req-1",
        "status": "applied",
        "customResolved": True,
    }
    monkeypatch.setattr(
        agent_routes.agent_tool_governance_service,
        "resolve_tool_governance_request",
        lambda *_args, **_kwargs: expected_resolved,
    )
    resolved = client.patch(
        "/api/agents/agent-live/tool-governance-requests/req-1",
        json={"decision": "approve", "resolvedBy": "user", "resolutionNote": "approve"},
    )
    assert resolved.status_code == 200
    assert resolved.json() == expected_resolved

    expected_consumed = {
        "messageId": "msg-1",
        "status": "consumed",
        "customConsumed": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "consume_agent_inbox_message",
        lambda *_args, **_kwargs: expected_consumed,
    )
    consumed_response = client.post(
        "/api/agents/agent-live/messages/msg-1/consume",
        json={"consumedBySessionId": "session-1", "consumedByTurnId": "agent-center"},
    )
    assert consumed_response.status_code == 200
    assert consumed_response.json() == expected_consumed

    expected_consume_all = {
        "agentId": "agent-live",
        "consumed": True,
        "consumedCount": 2,
        "remainingPendingCount": 0,
        "customConsumeAll": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "consume_all_agent_inbox_messages",
        lambda *_args, **_kwargs: expected_consume_all,
    )
    consume_all_response = client.post(
        "/api/agents/agent-live/messages/consume-all",
        json={"consumedBySessionId": "session-1", "consumedByTurnId": "agent-center"},
    )
    assert consume_all_response.status_code == 200
    assert consume_all_response.json() == expected_consume_all

    expected_membership = {
        "schemaVersion": 1,
        "modes": {"chat": {"customMode": True}},
        "customMembership": True,
    }
    monkeypatch.setattr(agent_routes, "_ensure_config_agent_instances", lambda: None)
    monkeypatch.setattr(agent_routes, "invalidate_agent_config_workspace_cache", lambda: None)
    monkeypatch.setattr(
        agent_routes,
        "update_agent_mode_membership",
        lambda *_args, **_kwargs: expected_membership,
    )
    membership_response = client.patch(
        "/api/agents/agent-live/mode-membership",
        json={"chatDefault": True, "chatAvailable": True, "researchPool": False},
    )
    assert membership_response.status_code == 200
    assert membership_response.json() == expected_membership
