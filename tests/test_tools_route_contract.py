"""Tool-registry JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.tools_models import (
    ToolBulkActionResponse,
    ToolDeleteResponse,
    ToolGeneratedItemResponse,
    ToolImage2ModelsResponse,
    ToolRegistryResponse,
    ToolTestResponse,
    ToolWebSearchHealthResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "tools.py"

JSON_ROUTE_FUNCTIONS = {
    "tools_registry",
    "tools_web_search_health",
    "tools_image2_models",
    "tools_image2_default_model",
    "tools_generated_create",
    "tools_generated_validate",
    "tools_generated_enabled",
    "tools_generated_bulk_enabled",
    "tools_bulk_delete",
    "tools_delete",
    "tools_test",
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


def test_tools_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"tools JSON routes must declare response_model: {missing}"


def test_tools_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ToolRegistryResponse: {"schemaVersion", "counts", "agentScopes", "tools"},
        ToolWebSearchHealthResponse: {"toolId", "available"},
        ToolImage2ModelsResponse: {"toolId", "defaultModelRef", "selectedModel"},
        ToolGeneratedItemResponse: {"id", "name", "validated", "enabled"},
        ToolBulkActionResponse: {"successCount", "skippedCount", "failedCount", "results"},
        ToolDeleteResponse: {"deleted", "toolId"},
        ToolTestResponse: {"status", "called", "testPolicy", "agentCompatibility"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_tools_models_keep_unknown_fields_without_injecting_defaults() -> None:
    registry = ToolRegistryResponse.model_validate(
        {"counts": {"builtIn": 1}, "tools": [{"name": "grep_search_tool", "custom": True}]}
    ).model_dump(exclude_unset=True)
    assert registry == {
        "counts": {"builtIn": 1},
        "tools": [{"name": "grep_search_tool", "custom": True}],
    }
    assert "agentScopes" not in registry

    image2 = ToolImage2ModelsResponse.model_validate(
        {
            "toolId": "image2_generate_tool",
            "defaultModelRef": "image_model",
            "selectedModel": {"modelRef": "image_model", "custom": 1},
        }
    ).model_dump(exclude_unset=True)
    assert image2["selectedModel"]["custom"] == 1
    assert "models" not in image2

    test = ToolTestResponse.model_validate(
        {"status": "blocked", "called": False, "testPolicy": {"mode": "blocked"}}
    ).model_dump(exclude_unset=True)
    assert test == {
        "status": "blocked",
        "called": False,
        "testPolicy": {"mode": "blocked"},
    }
    assert "timeout" not in test
