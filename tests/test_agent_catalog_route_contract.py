"""A1 contract: agent catalog JSON routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_catalog_models import (
    AgentAvatarOptionsResponse,
    AgentConfigWorkspaceResponse,
    AgentDocumentResponse,
    AgentResetResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_list",
    "agent_avatar_options",
    "agent_config_workspace",
    "agent_create",
    "agent_detail",
    "agent_update",
    "agent_reset",
    "agent_archive",
}


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(AGENTS_ROUTE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                found[node.name] = decorator
    return found


def test_agent_catalog_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"agent catalog JSON routes must declare response_model: {missing}"


def test_agent_avatar_image_declares_file_response_class() -> None:
    decorator = _route_decorators()["agent_avatar_image"]
    has_response_class = False
    for keyword in decorator.keywords:
        if keyword.arg != "response_class":
            continue
        if isinstance(keyword.value, ast.Constant) and keyword.value.value is None:
            continue
        has_response_class = True
    assert has_response_class, "GET /agents/avatar-image/{filename} must declare response_class"


def test_agent_catalog_response_models_keep_unknown_fields(monkeypatch) -> None:
    document = AgentDocumentResponse.model_validate(
        {
            "agentId": "agent-live",
            "displayName": "live",
            "customAgent": True,
        }
    )
    document_dump = document.model_dump(exclude_unset=True)
    assert document_dump["customAgent"] is True
    assert document_dump["agentId"] == "agent-live"

    workspace = AgentConfigWorkspaceResponse.model_validate(
        {
            "generatedAt": "now",
            "agents": [{"agentId": "agent-live", "customWorkspaceAgent": True}],
            "customWorkspace": True,
        }
    )
    workspace_dump = workspace.model_dump(exclude_unset=True)
    assert workspace_dump["customWorkspace"] is True
    assert workspace_dump["agents"][0]["customWorkspaceAgent"] is True

    avatar_options = AgentAvatarOptionsResponse.model_validate(
        {
            "modelId": "model-1",
            "items": [{"id": "a", "customAvatar": True}],
            "customOptions": True,
        }
    )
    avatar_dump = avatar_options.model_dump(exclude_unset=True)
    assert avatar_dump["customOptions"] is True
    assert avatar_dump["items"][0]["customAvatar"] is True

    reset = AgentResetResponse.model_validate(
        {
            "agent": {"agentId": "agent-live", "customResetAgent": True},
            "resetSummary": {"resetDirectSession": True, "customReset": True},
            "customResetEnvelope": True,
        }
    )
    reset_dump = reset.model_dump(exclude_unset=True)
    assert reset_dump["customResetEnvelope"] is True
    assert reset_dump["agent"]["customResetAgent"] is True
    assert reset_dump["resetSummary"]["customReset"] is True

    monkeypatch.setattr(agent_routes, "_ensure_config_agent_instances", lambda: None)

    expected_list = [
        {
            "agentId": "agent-live",
            "displayName": "live",
            "customAgent": True,
        }
    ]
    monkeypatch.setattr(agent_routes, "list_agents", lambda **_kwargs: expected_list)
    listed = client.get("/api/agents?detail=summary")
    assert listed.status_code == 200
    assert listed.json() == expected_list

    expected_detail = {
        "agentId": "agent-live",
        "displayName": "live",
        "customDetail": True,
    }
    monkeypatch.setattr(agent_routes, "get_agent", lambda *_args, **_kwargs: expected_detail)
    detail = client.get("/api/agents/agent-live")
    assert detail.status_code == 200
    assert detail.json() == expected_detail

    expected_workspace = {
        "generatedAt": "now",
        "agents": [{"agentId": "agent-live", "customWorkspaceAgent": True}],
        "customWorkspace": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "get_agent_config_workspace",
        lambda **_kwargs: expected_workspace,
    )
    workspace_response = client.get("/api/agents/config-workspace?includeRuntime=false")
    assert workspace_response.status_code == 200
    assert workspace_response.json() == expected_workspace

    expected_avatar_options = {
        "modelId": "model-1",
        "items": [{"id": "a", "customAvatar": True}],
        "customOptions": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "list_agent_avatar_options",
        lambda **_kwargs: expected_avatar_options,
    )
    avatar_response = client.get("/api/agents/avatar-options")
    assert avatar_response.status_code == 200
    assert avatar_response.json() == expected_avatar_options

    expected_reset = {
        "agent": {"agentId": "agent-live", "customResetAgent": True},
        "resetSummary": {"resetDirectSession": True, "customReset": True},
        "customResetEnvelope": True,
    }
    monkeypatch.setattr(agent_routes, "reset_agent_instance", lambda *_args, **_kwargs: expected_reset)
    reset_response = client.post(
        "/api/agents/agent-live/reset",
        json={"resetDirectSession": True},
    )
    assert reset_response.status_code == 200
    assert reset_response.json() == expected_reset
