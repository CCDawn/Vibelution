"""Evolution JSON/SSE response contract regressions."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.routes import evolution as evolution_routes
from core.web.routes.evolution_models import (
    EvolutionChatReviewCandidateResponse,
    EvolutionChatReviewQueueResponse,
    EvolutionCommandStatusResponse,
    EvolutionDeletedResponse,
    EvolutionJsonResponse,
    EvolutionLibraryResponse,
    EvolutionOverviewResponse,
    EvolutionProposalResponse,
    EvolutionRunResponse,
    EvolutionSelfWorkspaceSnapshotResponse,
    EvolutionWorkspaceSnapshotResponse,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "evolution.py"

client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

JSON_ROUTE_FUNCTIONS = {
    "evolution_overview",
    "evolution_workspace_snapshot",
    "self_evolution_workspace_snapshot",
    "evolution_runs",
    "evolution_library",
    "evolution_proposal_detail",
    "evolution_update_proposal",
    "evolution_delete_proposal",
    "evolution_bulk_delete_proposals",
    "evolution_workbench",
    "evolution_chat_review",
    "evolution_chat_review_candidate",
    "evolution_self_candidates",
    "evolution_chat_review_bulk_delete",
    "evolution_chat_review_approve",
    "evolution_chat_review_reject",
    "evolution_chat_review_decision",
    "evolution_active_run",
    "evolution_latest_run",
    "evolution_run_command_status",
    "evolution_worktree_runs",
    "evolution_worktree_active_run",
    "evolution_start_worktree_run",
    "self_evolution_start_worktree_run",
    "self_observation_start_run",
    "self_observation_run",
    "self_observation_run_action",
    "self_evolution_start_autonomous_run",
    "self_evolution_active_autonomous_run",
    "self_evolution_latest_autonomous_run",
    "self_evolution_autonomous_run",
    "self_evolution_autonomous_run_action",
    "evolution_worktree_run",
    "evolution_worktree_run_action",
    "evolution_start_run",
    "evolution_pause_run",
    "evolution_resume_run",
    "evolution_retry_run",
    "evolution_terminate_run",
    "evolution_delete_run",
    "evolution_run_action",
    "self_evolution_overview",
    "self_evolution_transactions",
    "self_evolution_delete_history",
    "self_evolution_audit",
}

SSE_ROUTE_FUNCTIONS = {
    "evolution_active_run_events",
    "self_observation_run_events",
    "evolution_worktree_run_events",
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


def test_evolution_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"evolution JSON routes must declare response_model: {missing}"


def test_evolution_sse_routes_declare_streaming_response_class() -> None:
    decorators = _route_decorators()
    missing = []
    for name in sorted(SSE_ROUTE_FUNCTIONS):
        decorator = decorators.get(name)
        if decorator is None:
            missing.append(name)
            continue
        has_response_class = any(
            keyword.arg == "response_class"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "StreamingResponse"
            for keyword in decorator.keywords
        )
        has_response_model = any(keyword.arg == "response_model" for keyword in decorator.keywords)
        if not has_response_class or has_response_model:
            missing.append(name)
    assert missing == [], f"evolution SSE routes must declare response_class only: {missing}"
    decorated = set(_route_decorators())
    assert decorated == JSON_ROUTE_FUNCTIONS | SSE_ROUTE_FUNCTIONS


def test_evolution_models_publish_known_schema_fields() -> None:
    expected_properties = {
        EvolutionOverviewResponse: {"currentStatus", "workbench", "recentRuns"},
        EvolutionWorkspaceSnapshotResponse: {
            "overview",
            "runs",
            "library",
            "workbench",
            "activeRun",
            "latestRun",
            "latestClosedLoopRecord",
            "worktreeActiveRun",
            "selfOverview",
        },
        EvolutionSelfWorkspaceSnapshotResponse: {
            "overview",
            "transactions",
            "worktreeActiveRun",
            "observationActiveRun",
            "autonomousActiveRun",
            "autonomousLatestRun",
        },
        EvolutionLibraryResponse: {"items", "pending"},
        EvolutionProposalResponse: {"sessionId", "sourceRun", "canEdit", "canDelete"},
        EvolutionRunResponse: {"runId", "id", "status"},
        EvolutionCommandStatusResponse: {"commandId", "status"},
        EvolutionChatReviewQueueResponse: {"enabled", "pendingCount", "counts"},
        EvolutionChatReviewCandidateResponse: {"candidateId", "id", "status"},
        EvolutionDeletedResponse: {"deleted", "deletedCount"},
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_evolution_models_keep_unknown_fields_without_injecting_defaults() -> None:
    snapshot = EvolutionWorkspaceSnapshotResponse.model_validate(
        {
            "overview": {"currentStatus": {"state": "idle"}},
            "runs": [],
            "library": {"items": [], "pending": []},
            "activeRun": None,
            "latestRun": None,
            "customSnapshot": True,
        }
    ).model_dump(exclude_unset=True)
    assert snapshot["activeRun"] is None
    assert snapshot["latestRun"] is None
    assert snapshot["customSnapshot"] is True
    assert "selfOverview" not in snapshot

    run = EvolutionRunResponse.model_validate(
        {"runId": "run-1", "status": "running", "customRun": True}
    ).model_dump(exclude_unset=True)
    assert run == {"runId": "run-1", "status": "running", "customRun": True}
    assert "proposalStatus" not in run

    empty_run = EvolutionRunResponse.model_validate({}).model_dump(exclude_unset=True)
    assert empty_run == {}

    library = EvolutionLibraryResponse.model_validate(
        {"items": [{"id": "p1", "customItem": True}], "customLibrary": True}
    ).model_dump(exclude_unset=True)
    assert library["items"][0]["customItem"] is True
    assert library["customLibrary"] is True
    assert "pending" not in library

    extras = EvolutionJsonResponse.model_validate({"leaseId": "keep-me"}).model_dump(exclude_unset=True)
    assert extras == {"leaseId": "keep-me"}


def test_evolution_json_routes_keep_unknown_fields(monkeypatch) -> None:
    expected_overview = {
        "currentStatus": {"state": "idle", "customStatus": True},
        "customOverview": True,
    }
    monkeypatch.setattr(evolution_routes, "get_evolution_overview", lambda: expected_overview)
    overview = client.get("/api/evolution/overview")
    assert overview.status_code == 200
    assert overview.json() == expected_overview

    monkeypatch.setattr(
        evolution_routes,
        "get_evolution_workspace_dashboard",
        lambda: {
            "overview": {"currentStatus": {"state": "idle"}},
            "runs": [],
            "library": {"items": [], "pending": []},
        },
    )
    monkeypatch.setattr(evolution_routes, "get_active_supervised_run", lambda: None)
    monkeypatch.setattr(
        evolution_routes,
        "get_supervised_workbench",
        lambda **_kwargs: {"source": "dataset", "activeRun": None},
    )
    monkeypatch.setattr(
        evolution_routes,
        "get_latest_supervised_run",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        evolution_routes,
        "_reviewable_supervised_closed_loop_record",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        evolution_routes,
        "current_supervised_agent_bindings_snapshot",
        lambda: {"agentBindings": {}, "bindingSource": "current_agent_config", "status": "error", "issues": []},
    )
    monkeypatch.setattr(evolution_routes, "get_self_evolution_light_overview", lambda: {"enabled": False})
    monkeypatch.setattr(evolution_routes, "get_active_supervised_worktree_run", lambda: None)
    monkeypatch.setattr(evolution_routes, "list_supervised_worktree_runs", lambda: [])
    monkeypatch.setattr(
        evolution_routes,
        "build_workspace_runtime_projection",
        lambda **_kwargs: {"active": None, "activeRuns": [], "byKind": {}, "customRuntime": True},
    )

    snapshot = client.get("/api/evolution/workspace-snapshot")
    assert snapshot.status_code == 200
    body = snapshot.json()
    assert body["activeRun"] is None
    assert body["latestRun"] is None
    assert body["latestClosedLoopRecord"] is None
    assert body["worktreeActiveRun"] is None
    assert body["evolutionRuntime"]["customRuntime"] is True

    monkeypatch.setattr(evolution_routes, "get_active_supervised_run", lambda: None)
    active = client.get("/api/evolution/active-run")
    assert active.status_code == 200
    assert active.json() is None

    expected_run = {"runId": "run-1", "status": "running", "customRun": True}
    monkeypatch.setattr(
        evolution_routes,
        "start_supervised_run",
        lambda *_args, **_kwargs: expected_run,
    )
    started = client.post("/api/evolution/runs", json={"sourceKind": "dataset"})
    assert started.status_code == 202
    assert started.json() == expected_run
