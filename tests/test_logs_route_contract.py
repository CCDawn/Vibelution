"""Log JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.logs_models import (
    LogContentResponse,
    LogDeleteResponse,
    LogRootItem,
    LogTreeResponse,
    RuntimeSceneDeleteResponse,
    RuntimeSceneDetailResponse,
    RuntimeSceneListItem,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "logs.py"

JSON_ROUTE_FUNCTIONS = {
    "log_roots",
    "log_tree",
    "log_content",
    "runtime_scene_list",
    "runtime_scene_detail",
    "runtime_scene_content",
    "clear_log",
    "delete_logs",
    "delete_runtime_scene_bundles",
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


def test_logs_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"logs JSON routes must declare response_model: {missing}"


def test_logs_models_publish_known_schema_fields() -> None:
    expected_properties = {
        LogRootItem: {"id", "path", "exists", "summary"},
        LogTreeResponse: {"root", "nodes"},
        LogContentResponse: {
            "rootId",
            "relativePath",
            "path",
            "content",
            "truncated",
            "diagnostics",
        },
        LogDeleteResponse: {"deletedCount", "deletedPaths", "missingPaths"},
        RuntimeSceneListItem: {
            "runtimeSceneId",
            "displayName",
            "packageIndex",
            "eventCount",
        },
        RuntimeSceneDetailResponse: {
            "runtimeSceneId",
            "displayName",
            "packageIndex",
            "status",
            "timeline",
            "packageSummary",
        },
        RuntimeSceneDeleteResponse: {"deletedCount", "deletedSceneIds"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_logs_models_keep_unknown_fields_without_injecting_defaults() -> None:
    root = LogRootItem.model_validate(
        {"id": "runtime_logs", "path": "logs", "exists": True, "summary": {"fileCount": 1}}
    ).model_dump(exclude_unset=True)
    assert root == {
        "id": "runtime_logs",
        "path": "logs",
        "exists": True,
        "summary": {"fileCount": 1},
    }

    content = LogContentResponse.model_validate(
        {"relativePath": "turns/latest.md", "content": "# latest", "futureHint": True}
    ).model_dump(exclude_unset=True)
    assert content == {
        "relativePath": "turns/latest.md",
        "content": "# latest",
        "futureHint": True,
    }
    assert "truncated" not in content

    scene = RuntimeSceneListItem.model_validate(
        {
            "runtimeSceneId": "scene-a",
            "packageIndex": {"packageId": "scene-a", "custom": 1},
        }
    ).model_dump(exclude_unset=True)
    assert scene == {
        "runtimeSceneId": "scene-a",
        "packageIndex": {"packageId": "scene-a", "custom": 1},
    }
    assert "eventCount" not in scene
