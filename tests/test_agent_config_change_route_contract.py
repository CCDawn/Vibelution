"""A2 contract: agent config-change JSON routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_config_change_models import (
    AgentConfigChangesResponse,
    AgentConfigDraftDiscardResponse,
    AgentConfigDraftResponse,
    AgentModelPromotionResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_config_changes",
    "agent_config_draft_create",
    "agent_config_draft_discard",
    "agent_model_promote",
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


def test_agent_config_change_routes_declare_response_model() -> None:
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
    assert missing == [], f"agent config-change routes must declare response_model: {missing}"


def test_agent_config_change_response_models_keep_unknown_fields(monkeypatch) -> None:
    changes = AgentConfigChangesResponse.model_validate(
        {
            "agentId": "agent-live",
            "schemaVersion": 1,
            "activeDraft": {"draftId": "draft-1", "customDraft": True},
            "customChanges": True,
        }
    )
    changes_dump = changes.model_dump(exclude_unset=True)
    assert changes_dump["customChanges"] is True
    assert changes_dump["activeDraft"]["customDraft"] is True

    draft = AgentConfigDraftResponse.model_validate(
        {
            "draftId": "draft-1",
            "agentId": "agent-live",
            "customDraft": True,
        }
    )
    assert draft.model_dump(exclude_unset=True)["customDraft"] is True

    discarded = AgentConfigDraftDiscardResponse.model_validate(
        {
            "draftId": "draft-1",
            "status": "discarded",
            "customDiscard": True,
        }
    )
    assert discarded.model_dump(exclude_unset=True)["customDiscard"] is True

    promoted = AgentModelPromotionResponse.model_validate(
        {
            "modelRef": "model-1",
            "agent": {"agentId": "agent-live", "customAgent": True},
            "customPromote": True,
        }
    )
    promoted_dump = promoted.model_dump(exclude_unset=True)
    assert promoted_dump["customPromote"] is True
    assert promoted_dump["agent"]["customAgent"] is True

    expected_changes = {
        "schemaVersion": 1,
        "agentId": "agent-live",
        "activeDraft": {"draftId": "draft-1", "customDraft": True},
        "revisions": [{"revisionId": "rev-1", "customRevision": True}],
        "customChanges": True,
    }
    monkeypatch.setattr(
        agent_routes.agent_config_change_service,
        "list_agent_config_changes",
        lambda *_args, **_kwargs: expected_changes,
    )
    listed = client.get("/api/agents/agent-live/config-changes")
    assert listed.status_code == 200
    assert listed.json() == expected_changes

    expected_draft = {
        "draftId": "draft-1",
        "agentId": "agent-live",
        "baseUpdatedAt": "now",
        "customDraft": True,
    }
    monkeypatch.setattr(
        agent_routes.agent_config_change_service,
        "save_agent_config_draft",
        lambda *_args, **_kwargs: expected_draft,
    )
    created = client.post(
        "/api/agents/agent-live/config-drafts",
        json={"baseUpdatedAt": "now", "snapshot": {"displayName": "live"}, "summary": "draft"},
    )
    assert created.status_code == 201
    assert created.json() == expected_draft

    expected_discard = {
        "draftId": "draft-1",
        "status": "discarded",
        "customDiscard": True,
    }
    monkeypatch.setattr(
        agent_routes.agent_config_change_service,
        "discard_agent_config_draft",
        lambda *_args, **_kwargs: expected_discard,
    )
    discarded_response = client.delete("/api/agents/agent-live/config-drafts/draft-1")
    assert discarded_response.status_code == 200
    assert discarded_response.json() == expected_discard

    expected_promote = {
        "status": "completed",
        "modelRef": "model-1",
        "source": "discovered",
        "agent": {"agentId": "agent-live", "customAgent": True},
        "customPromote": True,
    }
    monkeypatch.setattr(agent_routes, "promote_agent_model", lambda *_args, **_kwargs: expected_promote)
    promoted_response = client.post(
        "/api/agents/agent-live/llm-bindings/primary/promote",
        json={
            "modelRef": "model-1",
            "expectedBaseHash": "hash-1",
            "expectedAgentUpdatedAt": "now",
            "confirmed": True,
        },
    )
    assert promoted_response.status_code == 200
    assert promoted_response.json() == expected_promote
