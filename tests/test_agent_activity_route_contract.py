"""A3 contract: agent activity read routes are typed without rewriting documents."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import agents as agent_routes
from core.web.routes.agent_activity_models import (
    AgentInboxMessageResponse,
    AgentRunHistoryResponse,
    AgentRuntimeEvidenceResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROUTE = REPO_ROOT / "core" / "web" / "routes" / "agents.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "agent_run_list",
    "agent_message_list",
    "agent_runtime_evidence",
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


def test_agent_activity_routes_declare_response_model() -> None:
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
    assert missing == [], f"agent activity routes must declare response_model: {missing}"


def test_agent_activity_response_models_keep_unknown_fields(monkeypatch) -> None:
    history = AgentRunHistoryResponse.model_validate(
        {
            "agentId": "agent-live",
            "limit": 12,
            "runs": [{"runId": "run-1", "customRun": True}],
            "customHistory": True,
        }
    )
    history_dump = history.model_dump(exclude_unset=True)
    assert history_dump["customHistory"] is True
    assert history_dump["runs"][0]["customRun"] is True

    message = AgentInboxMessageResponse.model_validate(
        {
            "messageId": "msg-1",
            "eventId": "evt-1",
            "customMessage": True,
        }
    )
    assert message.model_dump(exclude_unset=True)["customMessage"] is True

    evidence = AgentRuntimeEvidenceResponse.model_validate(
        {
            "agentId": "agent-live",
            "sessionId": "session-1",
            "matches": [{"runtimeSceneId": "scene-1", "customMatch": True}],
            "customEvidence": True,
        }
    )
    evidence_dump = evidence.model_dump(exclude_unset=True)
    assert evidence_dump["customEvidence"] is True
    assert evidence_dump["matches"][0]["customMatch"] is True

    monkeypatch.setattr(agent_routes, "get_agent", lambda *_args, **_kwargs: {"agentId": "agent-live"})

    expected_history = {
        "agentId": "agent-live",
        "limit": 12,
        "runs": [{"runId": "run-1", "customRun": True}],
        "subAgentRuns": [],
        "customHistory": True,
    }
    monkeypatch.setattr(agent_routes, "list_agent_runs_for_agent", lambda *_args, **_kwargs: expected_history)
    listed = client.get("/api/agents/agent-live/runs?limit=12")
    assert listed.status_code == 200
    assert listed.json() == expected_history

    expected_messages = [
        {
            "messageId": "msg-1",
            "eventId": "evt-1",
            "status": "pending",
            "customMessage": True,
        }
    ]
    monkeypatch.setattr(
        agent_routes,
        "list_agent_inbox_messages_for_agent",
        lambda *_args, **_kwargs: expected_messages,
    )
    messages = client.get("/api/agents/agent-live/messages?status=pending&limit=8")
    assert messages.status_code == 200
    assert messages.json() == expected_messages

    expected_evidence = {
        "agentId": "agent-live",
        "sessionId": "session-1",
        "runId": "",
        "matches": [{"runtimeSceneId": "scene-1", "customMatch": True}],
        "customEvidence": True,
    }
    monkeypatch.setattr(
        agent_routes,
        "list_runtime_scene_evidence_for_agent",
        lambda *_args, **_kwargs: expected_evidence,
    )
    evidence_response = client.get(
        "/api/agents/agent-live/runtime-evidence?sessionId=session-1&limit=5",
    )
    assert evidence_response.status_code == 200
    assert evidence_response.json() == expected_evidence
