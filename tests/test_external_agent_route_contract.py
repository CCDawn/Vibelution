"""External-agent JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.external_agent_models import (
    ExternalAgentAgentListResponse,
    ExternalAgentApprovalResponse,
    ExternalAgentConnectionShutdownResponse,
    ExternalAgentInfoResponse,
    ExternalAgentTaskResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "external_agent.py"

JSON_ROUTE_FUNCTIONS = {
    "external_agent_gateway_info",
    "external_agent_connection_shutdown",
    "list_external_agents",
    "start_external_agent_task",
    "get_external_agent_task",
    "resolve_external_agent_approval",
    "cancel_external_agent_task",
    "heartbeat_external_agent_task",
}


def _is_router_decorator(decorator: ast.Call) -> bool:
    function = decorator.func
    return (
        isinstance(function, ast.Attribute)
        and isinstance(function.value, ast.Name)
        and function.value.id.lower().endswith("router")
    )


def _route_decorators() -> dict[str, ast.Call]:
    tree = ast.parse(ROUTE_FILE.read_text(encoding="utf-8"))
    found: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and _is_router_decorator(decorator):
                found[node.name] = decorator
    return found


def test_external_agent_json_routes_declare_response_model() -> None:
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
        has_exclude_unset = any(
            keyword.arg == "response_model_exclude_unset"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
        if not has_response_model or not has_exclude_unset:
            missing.append(name)
    assert missing == [], f"external-agent JSON routes must declare response_model: {missing}"


def test_external_agent_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ExternalAgentInfoResponse: {
            "apiProtocolVersion",
            "serverVersion",
            "projectRoot",
            "runtimeSourceRevision",
            "enabled",
        },
        ExternalAgentConnectionShutdownResponse: {"status"},
        ExternalAgentAgentListResponse: {"status", "agents"},
        ExternalAgentTaskResponse: {"taskId", "status"},
        ExternalAgentApprovalResponse: {"status", "decision"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_external_agent_models_keep_unknown_fields_without_injecting_defaults() -> None:
    info = ExternalAgentInfoResponse.model_validate(
        {"enabled": False, "apiProtocolVersion": "1.0", "futureHint": True}
    ).model_dump(exclude_unset=True)
    assert info == {
        "enabled": False,
        "apiProtocolVersion": "1.0",
        "futureHint": True,
    }
    assert "projectRoot" not in info

    agents = ExternalAgentAgentListResponse.model_validate(
        {"status": "ok", "agents": [], "count": 0, "guideUri": "vibelution://guide"}
    ).model_dump(exclude_unset=True)
    assert agents == {
        "status": "ok",
        "agents": [],
        "count": 0,
        "guideUri": "vibelution://guide",
    }

    task = ExternalAgentTaskResponse.model_validate(
        {"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"}
    ).model_dump(exclude_unset=True)
    assert task == {"taskId": "eat-1", "status": "running", "_leaseId": "lease-1"}
    assert "resultSummary" not in task

    approval = ExternalAgentApprovalResponse.model_validate(
        {"status": "ok", "decision": "accept", "taskId": "eat-1"}
    ).model_dump(exclude_unset=True)
    assert approval == {"status": "ok", "decision": "accept", "taskId": "eat-1"}
