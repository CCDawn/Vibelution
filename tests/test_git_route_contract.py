"""Git JSON response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from core.web.routes.git_models import (
    GitCommitListResponse,
    GitCommitMessageModelResponse,
    GitCommitMessagePromptResponse,
    GitCommitMessageResponse,
    GitCommitResponse,
    GitFileDiffResponse,
    GitObjectDetailResponse,
    GitStatusResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "git.py"

JSON_ROUTE_FUNCTIONS = {
    "git_status",
    "git_commits",
    "git_diff",
    "git_object_detail",
    "git_commit_message",
    "git_commit_message_default_model",
    "git_commit_message_prompt",
    "git_commit",
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


def test_git_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"git JSON routes must declare response_model: {missing}"


def test_git_models_publish_known_schema_fields() -> None:
    expected_properties = {
        GitStatusResponse: {
            "available",
            "error",
            "branch",
            "headRevShort",
            "upstream",
            "dirty",
            "requiresAttention",
            "statusLevel",
            "summary",
            "counts",
            "localCommits",
            "worktrees",
            "files",
            "totalFiles",
            "truncated",
        },
        GitCommitListResponse: {"available", "error", "commits"},
        GitFileDiffResponse: {
            "available",
            "path",
            "statusLabel",
            "diff",
            "language",
        },
        GitObjectDetailResponse: {"kind", "statusLabel", "diff", "meta"},
        GitCommitMessageResponse: {"message", "modelId", "files"},
        GitCommitMessageModelResponse: {"modelId", "previousModelId"},
        GitCommitMessagePromptResponse: {"prompt", "promptChars"},
        GitCommitResponse: {"committed", "shortSha", "files"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_git_models_keep_unknown_fields_without_injecting_defaults() -> None:
    status = GitStatusResponse.model_validate(
        {
            "available": True,
            "dirty": True,
            "upstream": {"name": "origin/main", "ahead": 2},
            "futureHint": True,
        }
    ).model_dump(exclude_unset=True)
    assert status == {
        "available": True,
        "dirty": True,
        "upstream": {"name": "origin/main", "ahead": 2},
        "futureHint": True,
    }
    assert "files" not in status

    message = GitCommitMessageResponse.model_validate(
        {"message": "feat: git", "modelId": "local", "files": ["git.py"]}
    ).model_dump(exclude_unset=True)
    assert message == {"message": "feat: git", "modelId": "local", "files": ["git.py"]}
    assert "profileId" not in message

    commit = GitCommitResponse.model_validate(
        {"committed": True, "shortSha": "abcdef123456"}
    ).model_dump(exclude_unset=True)
    assert commit == {"committed": True, "shortSha": "abcdef123456"}
    assert "commitSha" not in commit
