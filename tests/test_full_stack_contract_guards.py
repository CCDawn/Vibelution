"""Incremental guards for the canonical full-stack feature contract.

The budgets preserve current behavior while preventing new structural debt.
They may stay equal or decrease; increases require an explicit migration
exception in docs/standards/development-standard.md section 24.4.
"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTES_ROOT = REPO_ROOT / "core" / "web" / "routes"
HTTP_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "api_route",
}

# Transitional debt ledger. New JSON endpoints must declare response_model.
# Keys are paths relative to core/web/routes/ (posix). Package modules use
# "team_workflows/<module>.py" after the monolith split of team_workflows.py.
LEGACY_UNTYPED_ENDPOINT_BUDGETS: dict[str, int] = {
    "agents.py": 46,
    "chat_rooms.py": 11,
    "cli_agents.py": 6,
    "computer_use.py": 5,
    "config.py": 31,
    "conversations.py": 1,
    "data_processing.py": 11,
    "diagnostics.py": 1,
    "evolution.py": 48,
    "files.py": 2,
    "git.py": 8,
    "kernel.py": 8,
    "knowledge.py": 34,
    "launcher.py": 26,
    "logs.py": 9,
    "memory.py": 13,
    "pet.py": 2,
    "project_agent_bus.py": 3,
    "research.py": 26,
    "research_evidence.py": 8,
    "research_loop.py": 6,
    "reset.py": 3,
    "runtime.py": 6,
    "sessions.py": 22,
    "skills.py": 2,
    "team_templates.py": 3,
    "team_workflows/experiment.py": 22,
    "team_workflows/knowledge.py": 9,
    "team_workflows/orchestration.py": 2,
    "team_workflows/research_ops.py": 23,
    "team_workflows/research_projects.py": 4,
    "team_workflows/source_collection.py": 9,
    "team_workflows/stage_rounds.py": 2,
    "teams.py": 13,
    "tools.py": 11,
    "usage.py": 1,
    "user_content.py": 6,
    "workbench_ui.py": 2,
}


def _router_method(decorator: ast.expr) -> tuple[str, ast.Call] | None:
    if not isinstance(decorator, ast.Call):
        return None
    function = decorator.func
    if (
        not isinstance(function, ast.Attribute)
        or function.attr not in HTTP_METHODS
        or not isinstance(function.value, ast.Name)
        or not function.value.id.lower().endswith("router")
    ):
        return None
    return function.attr, decorator


def _has_explicit_response_contract(decorator: ast.Call) -> bool:
    for keyword in decorator.keywords:
        if keyword.arg not in {"response_model", "response_class"}:
            continue
        return not (
            isinstance(keyword.value, ast.Constant)
            and keyword.value.value is None
        )
    return False


def _untyped_endpoint_count(source: str, *, filename: str = "<source>") -> int:
    tree = ast.parse(source, filename=filename)
    count = 0
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            match = _router_method(decorator)
            if match is None:
                continue
            _, call = match
            if not _has_explicit_response_contract(call):
                count += 1
    return count


def _iter_route_modules() -> list[Path]:
    """Public route modules: top-level *.py and package modules (skip private _*.py / __init__)."""
    modules: list[Path] = []
    for path in sorted(ROUTES_ROOT.rglob("*.py")):
        if path.name == "__init__.py" or path.name.startswith("_"):
            continue
        modules.append(path)
    return modules


def _route_ledger_key(path: Path) -> str:
    return path.relative_to(ROUTES_ROOT).as_posix()


def _current_untyped_endpoint_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_route_modules():
        count = _untyped_endpoint_count(
            path.read_text(encoding="utf-8"),
            filename=str(path),
        )
        if count:
            counts[_route_ledger_key(path)] = count
    return counts


def test_response_model_guard_recognizes_typed_and_untyped_routes() -> None:
    source = """
@router.get("/typed", response_model=TypedPayload)
def typed():
    return {}

@router.get("/stream", response_class=StreamingResponse)
def stream():
    return StreamingResponse(iter(()))

@router.post("/untyped")
async def untyped():
    return {}
"""
    assert _untyped_endpoint_count(source) == 1


def test_route_module_scan_includes_team_workflows_package() -> None:
    keys = {_route_ledger_key(path) for path in _iter_route_modules()}
    assert "sessions.py" in keys
    assert "team_workflows/source_collection.py" in keys
    assert "team_workflows.py" not in keys
    assert not any(key.startswith("team_workflows/_") for key in keys)


def test_fastapi_response_contract_debt_does_not_grow() -> None:
    current = _current_untyped_endpoint_counts()
    paths = set(current) | set(LEGACY_UNTYPED_ENDPOINT_BUDGETS)
    drift = {
        path: {
            "current": current.get(path, 0),
            "budget": LEGACY_UNTYPED_ENDPOINT_BUDGETS.get(path, 0),
        }
        for path in sorted(paths)
        if current.get(path, 0) != LEGACY_UNTYPED_ENDPOINT_BUDGETS.get(path, 0)
    }
    assert drift == {}, (
        "New public JSON endpoints must declare an explicit response_model; "
        "non-JSON endpoints must declare response_class. Lower the recorded "
        "budget when legacy debt is removed. Move response DTOs into the route "
        f"contract and keep domain behavior in services. Drift: {drift}"
    )


def test_response_contract_debt_ledger_points_to_existing_routes() -> None:
    missing = sorted(
        key
        for key in LEGACY_UNTYPED_ENDPOINT_BUDGETS
        if not (ROUTES_ROOT / key).is_file()
    )
    assert missing == []
