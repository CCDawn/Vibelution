"""Agent Kernel JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.kernel_models import (
    KernelEventDetailResponse,
    KernelEventLoopResponse,
    KernelInboxAckResponse,
    KernelInboxResponse,
    KernelTaskDetailResponse,
    KernelTaskListResponse,
    KernelTaskTimelineResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "kernel.py"

JSON_ROUTE_FUNCTIONS = {
    "kernel_agent_message_adapter_create",
    "kernel_event_create",
    "kernel_event_detail",
    "kernel_task_list",
    "kernel_task_timeline",
    "kernel_task_detail",
    "kernel_agent_inbox",
    "kernel_agent_inbox_ack",
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


def test_kernel_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"kernel JSON routes must declare response_model: {missing}"


def test_kernel_models_publish_known_schema_fields() -> None:
    expected_properties = {
        KernelEventLoopResponse: {
            "reused",
            "event",
            "task",
            "execution",
            "outcome",
            "proposals",
        },
        KernelEventDetailResponse: {"eventId", "status"},
        KernelTaskListResponse: {"tasks", "limit", "status", "updatedAt"},
        KernelTaskTimelineResponse: {
            "taskId",
            "task",
            "event",
            "execution",
            "outcome",
            "deliveries",
            "proposals",
            "runtimeEvidenceRefs",
            "projectionRefs",
            "timeline",
            "readModel",
        },
        KernelTaskDetailResponse: {"taskId", "status"},
        KernelInboxResponse: {"agentId", "status", "messages", "pendingCount", "updatedAt"},
        KernelInboxAckResponse: {"acked", "agentId", "eventId", "message"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_kernel_models_keep_unknown_fields_without_injecting_defaults() -> None:
    loop = KernelEventLoopResponse.model_validate(
        {
            "reused": False,
            "event": {"status": "accepted", "custom": 1},
            "adapter": {"source": "manual_api"},
        }
    ).model_dump(exclude_unset=True)
    assert loop == {
        "reused": False,
        "event": {"status": "accepted", "custom": 1},
        "adapter": {"source": "manual_api"},
    }
    assert "proposals" not in loop

    inbox = KernelInboxResponse.model_validate(
        {"agentId": "ag-1", "pendingCount": 1, "messages": [{"messageId": "m1"}]}
    ).model_dump(exclude_unset=True)
    assert inbox == {
        "agentId": "ag-1",
        "pendingCount": 1,
        "messages": [{"messageId": "m1"}],
    }
    assert "updatedAt" not in inbox
