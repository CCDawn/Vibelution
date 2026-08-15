"""Runtime JSON and SSE response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.runtime_models import (
    RuntimeBrowserTelemetryResponse,
    RuntimeCodeFreshnessResponse,
    RuntimeLifecycleCancelResponse,
    RuntimeLifecycleResponse,
    RuntimeSummaryResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "runtime.py"

JSON_ROUTE_FUNCTIONS = {
    "runtime_summary",
    "runtime_code_freshness",
    "runtime_shutdown",
    "runtime_restart",
    "runtime_lifecycle_command_cancel",
    "runtime_browser_telemetry",
}

STREAM_ROUTE = "runtime_events"


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


def test_runtime_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"runtime JSON routes must declare response_model: {missing}"


def test_runtime_events_declares_streaming_response_class() -> None:
    decorator = _route_decorators()[STREAM_ROUTE]
    has_response_class = any(
        keyword.arg == "response_class"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "StreamingResponse"
        for keyword in decorator.keywords
    )
    assert has_response_class
    source = ROUTE_FILE.read_text(encoding="utf-8")
    assert 'media_type="text/event-stream"' in source


def test_runtime_models_publish_known_schema_fields() -> None:
    expected_properties = {
        RuntimeSummaryResponse: {
            "status",
            "mode",
            "model",
            "profile",
            "agentName",
            "userName",
            "userProfile",
            "sessionState",
            "sessionStateLine",
            "sessionNeedsResponse",
            "sessionUpdatedAt",
            "mentalState",
            "contextCompression",
            "runtimeManager",
            "workbench",
            "workRuns",
            "lifecycleProof",
        },
        RuntimeCodeFreshnessResponse: {"schemaVersion", "verdict", "backend", "frontend"},
        RuntimeLifecycleResponse: {
            "accepted",
            "mode",
            "commandId",
            "message",
            "chatTurns",
            "chatRoomRounds",
            "evolutionRuns",
        },
        RuntimeLifecycleCancelResponse: {
            "cancelled",
            "status",
            "commandId",
            "operation",
            "message",
            "stateVersion",
        },
        RuntimeBrowserTelemetryResponse: {
            "accepted",
            "reason",
            "runtimeSceneId",
            "recordedAt",
            "indexed",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_runtime_models_keep_unknown_fields_without_injecting_defaults() -> None:
    summary = RuntimeSummaryResponse.model_validate(
        {
            "agentName": "Vibelution",
            "userProfile": {"displayName": "Ada", "customPref": True},
            "contextCompression": {"strategy": {"levels": [{"level": "light"}]}},
            "lifecycleProof": {"overallState": "ready", "components": {}},
            "futureHint": True,
        }
    ).model_dump(exclude_unset=True)
    assert summary == {
        "agentName": "Vibelution",
        "userProfile": {"displayName": "Ada", "customPref": True},
        "contextCompression": {"strategy": {"levels": [{"level": "light"}]}},
        "lifecycleProof": {"overallState": "ready", "components": {}},
        "futureHint": True,
    }

    freshness = RuntimeCodeFreshnessResponse.model_validate(
        {"verdict": "current", "backend": {"behind": False, "custom": 1}}
    ).model_dump(exclude_unset=True)
    assert freshness == {"verdict": "current", "backend": {"behind": False, "custom": 1}}

    lifecycle = RuntimeLifecycleResponse.model_validate(
        {"accepted": True, "mode": "runtime_manager", "chatTurns": []}
    ).model_dump(exclude_unset=True)
    assert lifecycle == {"accepted": True, "mode": "runtime_manager", "chatTurns": []}
    assert "commandId" not in lifecycle

    telemetry = RuntimeBrowserTelemetryResponse.model_validate(
        {"accepted": False, "reason": "no_runtime_scene"}
    ).model_dump(exclude_unset=True)
    assert telemetry == {"accepted": False, "reason": "no_runtime_scene"}
    assert "indexed" not in telemetry
