"""G4-2: research runtime JSON routes are typed; SSE keeps event-stream framing."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.web.routes.team_workflows import research_runtime as research_runtime_module
from core.web.routes.team_workflows.research_runtime_models import (
    ResearchWorkflowBindingConfigResponse,
    ResearchWorkflowBudgetResponse,
    ResearchWorkflowCampaignListResponse,
    ResearchWorkflowCommandReceiptResponse,
    ResearchWorkflowCreateRunResponse,
    ResearchWorkflowDefinitionResponse,
    ResearchWorkflowEffectiveBindingsResponse,
    ResearchWorkflowEvaluationResponse,
    ResearchWorkflowEventPageResponse,
    ResearchWorkflowHandoffDetailResponse,
    ResearchWorkflowHandoffListResponse,
    ResearchWorkflowHypothesisListResponse,
    ResearchWorkflowLaunchOptionsResponse,
    ResearchWorkflowLedgerResponse,
    ResearchWorkflowNodeDetailResponse,
    ResearchWorkflowRunListResponse,
    ResearchWorkflowRunSnapshotResponse,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / "core" / "web" / "routes" / "team_workflows" / "research_runtime.py"

JSON_ROUTE_FUNCTIONS = {
    "research_workflow_definition",
    "research_workflow_runs",
    "research_workflow_launch_options",
    "research_workflow_effective_bindings",
    "research_workflow_put_binding_config",
    "research_workflow_create_run",
    "research_workflow_run_snapshot",
    "research_workflow_node_detail",
    "research_workflow_events",
    "research_workflow_handoffs",
    "research_workflow_research_ledger",
    "research_workflow_budget",
    "research_workflow_hypotheses",
    "research_workflow_experiment_campaigns",
    "research_workflow_evaluation",
    "research_workflow_handoff_detail",
    "research_workflow_command",
}

STREAM_ROUTE = "research_workflow_event_stream"
SSE_FRAME = "id: run-1:1\nevent: node_running\ndata: {\"seq\":1,\"customEvent\":true}\n\n"


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


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(research_runtime_module.router, prefix="/api")
    return TestClient(app)


def test_research_runtime_json_routes_declare_response_model() -> None:
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
    assert missing == [], f"research runtime JSON routes must declare response_model: {missing}"


def test_research_runtime_stream_declares_streaming_response_class() -> None:
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
    assert '"Cache-Control": "no-cache, no-transform"' in source
    assert '"X-Accel-Buffering": "no"' in source


def test_research_runtime_models_publish_known_schema_fields() -> None:
    expected_properties = {
        ResearchWorkflowDefinitionResponse: {
            "workflowId",
            "workflowVersionId",
            "definition",
        },
        ResearchWorkflowRunListResponse: {"workflowId", "runs"},
        ResearchWorkflowLaunchOptionsResponse: {"workflowId", "teamId", "questions"},
        ResearchWorkflowEffectiveBindingsResponse: {
            "workflowId",
            "workflowVersionId",
            "teamId",
            "bindings",
        },
        ResearchWorkflowBindingConfigResponse: {
            "workflowId",
            "teamId",
            "workflowDefaults",
            "stageOverrides",
            "nodeOverrides",
            "updatedAt",
        },
        ResearchWorkflowCreateRunResponse: {
            "runId",
            "workflowId",
            "workflowVersionId",
            "teamId",
            "projectId",
            "questionId",
            "runVersion",
            "status",
        },
        ResearchWorkflowRunSnapshotResponse: {
            "run",
            "definition",
            "nodeAttempts",
            "activeNodeIds",
            "pendingHumanTasks",
            "commandOffers",
            "handoffSummary",
            "agentBindingSummary",
            "budgetSummary",
            "latestEventSequence",
            "generatedAt",
        },
        ResearchWorkflowNodeDetailResponse: {
            "runId",
            "teamId",
            "nodeId",
            "runVersion",
            "actorKind",
            "primaryRoleKey",
            "label",
            "runtimeCurrent",
            "status",
            "bindingSnapshotId",
            "latestAttempt",
            "attempts",
            "commandOffers",
            "latestEventSequence",
            "generatedAt",
            "agentId",
            "displayName",
            "resolvedFrom",
            "sessionId",
            "taskId",
            "turnId",
            "sessionAttempt",
            "chatDeepLink",
            "sessionAnchorDegraded",
            "blockedReason",
            "nodeAttempt",
        },
        ResearchWorkflowEventPageResponse: {
            "runId",
            "teamId",
            "runVersion",
            "latestEventSequence",
            "afterSequence",
            "lastReturnedSequence",
            "hasMore",
            "nextAfterSequence",
            "events",
        },
        ResearchWorkflowHandoffListResponse: {
            "runId",
            "teamId",
            "runVersion",
            "handoffs",
        },
        ResearchWorkflowLedgerResponse: {
            "runId",
            "teamId",
            "runVersion",
            "projectId",
            "claimEvidence",
            "teamKnowledge",
            "experimentPlanning",
            "nodeRuns",
            "handoffs",
            "artifactManifests",
            "resultPackage",
            "summary",
            "boundaries",
            "graph",
        },
        ResearchWorkflowBudgetResponse: {
            "runId",
            "teamId",
            "runVersion",
            "budgetLedgers",
            "budgetReservations",
        },
        ResearchWorkflowHypothesisListResponse: {
            "runId",
            "teamId",
            "runVersion",
            "hypothesisPortfolios",
        },
        ResearchWorkflowCampaignListResponse: {
            "runId",
            "teamId",
            "runVersion",
            "experimentCampaigns",
        },
        ResearchWorkflowEvaluationResponse: {
            "runId",
            "teamId",
            "runVersion",
            "competitionEvaluations",
            "qualityGateEvaluations",
        },
        ResearchWorkflowHandoffDetailResponse: {
            "runId",
            "teamId",
            "runVersion",
            "handoff",
            "fromNodeRun",
            "toNodeRun",
            "humanTask",
            "artifactManifests",
        },
        ResearchWorkflowCommandReceiptResponse: {
            "commandId",
            "runId",
            "status",
            "acceptedRunVersion",
            "idempotencyKey",
            "latestEventSequence",
            "problem",
        },
    }

    for model, expected in expected_properties.items():
        properties = set(model.model_json_schema().get("properties") or {})
        assert expected <= properties, (
            f"{model.__name__} is missing fields: {sorted(expected - properties)}"
        )


def test_research_runtime_response_models_keep_unknown_fields() -> None:
    definition = ResearchWorkflowDefinitionResponse.model_validate(
        {"workflowId": "challenge-cup-research", "customDef": True}
    )
    assert definition.model_dump(exclude_unset=True)["customDef"] is True

    snapshot = ResearchWorkflowRunSnapshotResponse.model_validate(
        {"runId": "r1", "nodes": [{"nodeId": "n1", "customNode": True}], "customSnap": True}
    )
    dumped = snapshot.model_dump(exclude_unset=True)
    assert dumped["customSnap"] is True
    assert dumped["nodes"][0]["customNode"] is True
    assert "status" not in dumped

    created = ResearchWorkflowCreateRunResponse.model_validate({"runId": "r1", "customCreate": True})
    assert created.model_dump(exclude_unset=True)["customCreate"] is True

    receipt = ResearchWorkflowCommandReceiptResponse.model_validate(
        {"commandId": "cmd-1", "customReceipt": True}
    )
    assert receipt.model_dump(exclude_unset=True)["customReceipt"] is True


def test_research_runtime_json_routes_keep_unknown_fields(monkeypatch) -> None:
    client = _client()
    expected_definition = {"workflowId": "challenge-cup-research", "customDef": True}

    class _Svc:
        def get_definition(self, workflow_id):
            assert workflow_id == "challenge-cup-research"
            return expected_definition

    monkeypatch.setattr(research_runtime_module, "_svc", lambda: _Svc())
    definition = client.get("/api/research/workflows/challenge-cup-research/definition")
    assert definition.status_code == 200
    assert definition.json() == expected_definition

    expected_snapshot = {"runId": "run-1", "customSnap": True, "nodes": [{"nodeId": "n1", "customNode": True}]}

    class _Snapshot:
        def to_dict(self):
            return expected_snapshot

    class _Query:
        def get_snapshot(self, **_kwargs):
            return _Snapshot()

    monkeypatch.setattr(research_runtime_module, "get_query_service", lambda: _Query())
    snapshot = client.get("/api/research/workflow-runs/run-1/snapshot", params={"teamId": "research-team"})
    assert snapshot.status_code == 200
    assert snapshot.json() == expected_snapshot

    expected_create = {"runId": "run-new", "customCreate": True}
    monkeypatch.setattr(
        research_runtime_module,
        "create_question_run",
        lambda *_args, **_kwargs: expected_create,
    )
    created = client.post(
        "/api/research/workflows/challenge-cup-research/runs",
        json={
            "teamId": "research-team",
            "questionId": "SCI-096",
            "idempotencyKey": "create-1",
            "safetyLimits": {
                "stageTokens": {"knowledge_collection": 1},
                "toolCalls": 1,
                "wallClockSeconds": 1,
                "maxRetries": 1,
            },
        },
    )
    assert created.status_code == 201
    assert created.json() == expected_create


def test_research_runtime_stream_keeps_event_stream_media_type_and_frames(monkeypatch) -> None:
    class _Stream:
        def validate_stream_request(self, **_kwargs):
            return None

        def iter_sse(self, **_kwargs):
            yield SSE_FRAME

    monkeypatch.setattr(research_runtime_module, "get_event_stream_service", lambda: _Stream())
    client = _client()
    response = client.get(
        "/api/research/workflow-runs/run-1/stream",
        params={"teamId": "research-team"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert SSE_FRAME.strip() in response.text
    assert "id: run-1:1" in response.text
    assert "event: node_running" in response.text
    assert '"customEvent":true' in response.text.replace(" ", "")
