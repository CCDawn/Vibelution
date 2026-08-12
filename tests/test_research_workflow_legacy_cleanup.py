"""T8 physical cleanup: old write routes and JSON writer are gone from production HTTP."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.research import router as research_router
from core.web.routes.team_workflows import research_runtime as research_runtime_module
from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    reset_formal_read_runtime_for_tests,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    reset_formal_write_runtime_for_tests,
)


PRODUCTION_ROOTS = (
    Path("core/web/routes"),
    Path("core/web/lifecycle.py"),
    Path("core/web/app.py"),
)


def _production_text() -> str:
    chunks: list[str] = []
    for root in PRODUCTION_ROOTS:
        if root.is_file():
            chunks.append(root.read_text(encoding="utf-8"))
            continue
        for path in root.rglob("*.py"):
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_legacy_write_routes_are_not_mounted() -> None:
    mounted = {getattr(route, "path", "") for route in research_router.routes}
    assert "/research/workflow-runs/{run_id}/nodes/{node_id}/commands" not in mounted
    assert "/research/workflow-runs/{run_id}/nodes/{node_id}/session-binding" not in mounted
    assert "/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve" not in mounted
    assert "/research/workflow-runs/{run_id}" not in mounted
    assert "/research/workflow-runs/{run_id}/canvas" not in mounted


def test_production_http_surface_does_not_import_json_writer() -> None:
    text = _production_text()
    assert "WorkflowRunStore" not in text
    assert "nodes/{node_id}/commands" not in text
    assert "session-binding" not in text
    assert "human-tasks/{task_id}/resolve" not in text


def test_snapshot_and_create_return_503_when_ledger_unavailable() -> None:
    reset_formal_read_runtime_for_tests()
    reset_formal_write_runtime_for_tests()
    app = FastAPI()
    app.include_router(research_runtime_module.router, prefix="/api")
    client = TestClient(app)
    snapshot = client.get(
        "/api/research/workflow-runs/run-missing/snapshot",
        params={"teamId": "research-team"},
    )
    assert snapshot.status_code == 503
    assert snapshot.json()["detail"]["code"] == "workflow_ledger_unavailable"

    created = client.post(
        "/api/research/workflows/challenge-cup-research/runs",
        json={
            "teamId": "research-team",
            "questionId": "SCI-096",
            "idempotencyKey": "create-1",
            "safetyLimits": {
                "stageTokens": {
                    "knowledge_collection": 250000,
                    "experiment_design": 250000,
                    "execution_iteration": 250000,
                },
                "toolCalls": 300,
                "wallClockSeconds": 21600,
                "maxRetries": 2,
            },
        },
    )
    assert created.status_code == 503
    assert created.json()["detail"]["code"] in {
        "workflow_ledger_unavailable",
        "workflow_migration_required",
    }

    listed = client.get(
        "/api/research/workflows/challenge-cup-research/runs",
        params={"teamId": "research-team"},
    )
    assert listed.status_code == 503
    assert listed.json()["detail"]["code"] in {
        "workflow_ledger_unavailable",
        "workflow_migration_required",
    }
