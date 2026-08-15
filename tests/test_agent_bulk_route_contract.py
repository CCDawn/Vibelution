"""A4 contract: agent bulk JSON routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_bulk_models import AgentBulkActionResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_bulk_archive",
    "agent_bulk_purge",
    "agent_bulk_prompt_template",
    "agent_bulk_config",
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


def test_agent_bulk_routes_declare_response_model() -> None:
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
    assert missing == [], f"agent bulk routes must declare response_model: {missing}"


def test_agent_bulk_response_models_keep_unknown_fields(monkeypatch) -> None:
    archive = AgentBulkActionResponse.model_validate(
        {
            "status": "ok",
            "requestedAgentIds": ["agent-live"],
            "success": [{"agentId": "agent-live", "customItem": True}],
            "customArchive": True,
        }
    )
    archive_dump = archive.model_dump(exclude_unset=True)
    assert archive_dump["customArchive"] is True
    assert archive_dump["success"][0]["customItem"] is True

    prompt = AgentBulkActionResponse.model_validate(
        {
            "status": "ok",
            "promptTemplateId": "tpl-1",
            "customPrompt": True,
        }
    )
    prompt_dump = prompt.model_dump(exclude_unset=True)
    assert prompt_dump["promptTemplateId"] == "tpl-1"
    assert prompt_dump["customPrompt"] is True

    config = AgentBulkActionResponse.model_validate(
        {
            "status": "ok",
            "appliedFields": ["displayName"],
            "customConfig": True,
        }
    )
    config_dump = config.model_dump(exclude_unset=True)
    assert config_dump["appliedFields"] == ["displayName"]
    assert config_dump["customConfig"] is True

    monkeypatch.setattr(agent_routes, "invalidate_agent_config_workspace_cache", lambda: None)

    expected_archive = {
        "status": "ok",
        "requestedAgentIds": ["agent-live"],
        "success": [{"agentId": "agent-live", "customItem": True}],
        "skipped": [],
        "failed": [],
        "summary": {"requestedCount": 1, "successCount": 1, "skippedCount": 0, "failedCount": 0},
        "customArchive": True,
    }
    monkeypatch.setattr(agent_routes, "bulk_archive_agents", lambda *_args, **_kwargs: expected_archive)
    archived = client.post("/api/agents/bulk-archive", json={"agentIds": ["agent-live"]})
    assert archived.status_code == 200
    assert archived.json() == expected_archive

    expected_purge = {
        "status": "ok",
        "requestedAgentIds": ["agent-live"],
        "success": [{"agentId": "agent-live", "customPurge": True}],
        "skipped": [],
        "failed": [],
        "summary": {"requestedCount": 1, "successCount": 1, "skippedCount": 0, "failedCount": 0},
        "customPurge": True,
    }
    monkeypatch.setattr(agent_routes, "bulk_purge_agents", lambda *_args, **_kwargs: expected_purge)
    purged = client.post("/api/agents/bulk-purge", json={"agentIds": ["agent-live"]})
    assert purged.status_code == 200
    assert purged.json() == expected_purge

    expected_prompt = {
        "status": "ok",
        "requestedAgentIds": ["agent-live"],
        "success": [{"agentId": "agent-live", "customPromptItem": True}],
        "skipped": [],
        "failed": [],
        "summary": {"requestedCount": 1, "successCount": 1, "skippedCount": 0, "failedCount": 0},
        "promptTemplateId": "tpl-1",
        "customPrompt": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "bulk_update_agent_prompt_template",
        lambda *_args, **_kwargs: expected_prompt,
    )
    prompted = client.post(
        "/api/agents/bulk-prompt-template",
        json={"agentIds": ["agent-live"], "promptTemplateId": "tpl-1"},
    )
    assert prompted.status_code == 200
    assert prompted.json() == expected_prompt

    expected_config = {
        "status": "ok",
        "requestedAgentIds": ["agent-live"],
        "success": [{"agentId": "agent-live", "customConfigItem": True}],
        "skipped": [],
        "failed": [],
        "summary": {"requestedCount": 1, "successCount": 1, "skippedCount": 0, "failedCount": 0},
        "appliedFields": ["displayName"],
        "customConfig": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "bulk_update_agent_config",
        lambda *_args, **_kwargs: expected_config,
    )
    configured = client.post(
        "/api/agents/bulk-config",
        json={"agentIds": ["agent-live"], "applyFields": ["displayName"], "patch": {"displayName": "Live"}},
    )
    assert configured.status_code == 200
    assert configured.json() == expected_config
