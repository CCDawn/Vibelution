"""G4-2: research runtime JSON routes are typed; SSE keeps event-stream framing."""

from __future__ import annotations

import ast
import json
from dataclasses import replace
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
from tests._support.workflow_ledger_helpers import (
    FIXED_NOW_MS,
    build_attempt_record,
    build_command_record,
    build_event_record,
    build_run_record,
)
from tests._support.workflow_ledger_http import ledger_http_client

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
            "rootSession",
            "scopedSessions",
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


def test_research_runtime_node_detail_route_reads_scoped_sessions_from_formal_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Exercise the actual route -> WorkflowQueryService -> Ledger path."""

    from core.web.services import session_service

    run_id = "run-http-scoped"
    node_run_id = "nr-http-scoped-hypothesis-design-1"
    root_session_id = "root-http"
    child_details = {
        "child-http-h2": {
            "id": "child-http-h2",
            "sessionKind": "child",
            "hiddenFromIndex": True,
            "agentId": "agent-hypothesis",
            "parentSessionId": root_session_id,
            "rootSessionId": root_session_id,
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "challenge-sci-096",
                "agentId": "agent-hypothesis",
                "workflowRunId": run_id,
                "workflowNodeId": "hypothesis_design",
                "selectionId": "selection-http",
                "candidateId": "H2",
                "scope": {
                    "version": 3,
                    "kind": "workflow_candidate",
                    "teamId": "research-team",
                    "researchProjectId": "challenge-sci-096",
                    "agentId": "agent-hypothesis",
                    "workflowRunId": run_id,
                    "workflowNodeId": "hypothesis_design",
                    "selectionId": "selection-http",
                    "candidateId": "H2",
                },
            },
        },
        "child-http-h1": {
            "id": "child-http-h1",
            "sessionKind": "child",
            "hiddenFromIndex": True,
            "agentId": "agent-hypothesis",
            "parentSessionId": root_session_id,
            "rootSessionId": root_session_id,
            "experimentBinding": {
                "teamId": "research-team",
                "researchProjectId": "challenge-sci-096",
                "agentId": "agent-hypothesis",
                "workflowRunId": run_id,
                "workflowNodeId": "hypothesis_design",
                "selectionId": "selection-http",
                "candidateId": "H1",
                "scope": {
                    "version": 3,
                    "kind": "workflow_candidate",
                    "teamId": "research-team",
                    "researchProjectId": "challenge-sci-096",
                    "agentId": "agent-hypothesis",
                    "workflowRunId": run_id,
                    "workflowNodeId": "hypothesis_design",
                    "selectionId": "selection-http",
                    "candidateId": "H1",
                },
            },
        },
    }

    def read_session(session_id: str, **_kwargs):
        if session_id == root_session_id:
            return {
                "id": root_session_id,
                "sessionKind": "main",
                "parentSessionId": None,
                "rootSessionId": root_session_id,
            }
        return child_details.get(session_id)

    monkeypatch.setattr(session_service, "get_session_detail", read_session)

    with ledger_http_client(tmp_path, monkeypatch) as (client, runtime):
        run = replace(
            build_run_record(
                run_id=run_id,
                status="running",
                last_event_sequence=1,
            ),
            active_node_id="hypothesis_design",
        )
        attempt = build_attempt_record(
            node_run_id=node_run_id,
            run_id=run_id,
            node_id="hypothesis_design",
            status="running",
            command_id="cmd-http-scoped",
        )
        anchor_payload = {
            "schemaVersion": 3,
            "rootSession": {
                "scopeKind": "workflow_node_root",
                "sessionId": root_session_id,
                "sessionAttempt": 1,
                "taskId": "root-task-http",
                "turnId": "root-turn-http",
                "status": "running",
            },
            # Keep the persisted order intentionally H2 -> H1.
            "scopedSessions": [
                {
                    "scopeKind": "workflow_candidate",
                    "selectionId": "selection-http",
                    "candidateId": "H2",
                    "sessionId": "child-http-h2",
                    "sessionAttempt": 2,
                    "taskId": "task-http-h2",
                    "turnId": "turn-http-h2",
                    "parentSessionId": root_session_id,
                    "rootSessionId": root_session_id,
                    "fragmentRefs": ["hypothesis_fragment:h2"],
                },
                {
                    "scopeKind": "workflow_candidate",
                    "selectionId": "selection-http",
                    "candidateId": "H1",
                    "sessionId": "child-http-h1",
                    "sessionAttempt": 1,
                    "taskId": "task-http-h1",
                    "turnId": "turn-http-h1",
                    "parentSessionId": root_session_id,
                    "rootSessionId": root_session_id,
                    "fragmentRefs": ["hypothesis_fragment:h1"],
                },
            ],
        }

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-http-scoped",
                    run_id=run_id,
                    node_id="hypothesis_design",
                    idempotency_key="http-scoped-start",
                )
            )
            uow.repository.insert_attempt(attempt)
            uow.repository.insert_anchor(
                anchor_id="anchor-http-scoped",
                node_run_id=node_run_id,
                actor_kind="agent",
                agent_id="agent-hypothesis",
                role_key="hypothesis_designer",
                # Legacy scalar columns point at a child on purpose. The
                # formal JSON root must remain authoritative for top-level
                # compatibility fields.
                session_id="child-http-h2",
                session_attempt=2,
                task_id="task-http-h2",
                turn_id="turn-http-h2",
                anchor_json=json.dumps(anchor_payload, ensure_ascii=False),
                created_at_ms=FIXED_NOW_MS,
            )

        runtime.store.submit(seed, force_flush=True).result(timeout=10)

        response = client.get(
            f"/api/research/workflow-runs/{run_id}/nodes/hypothesis_design",
            params={"teamId": "research-team"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rootSession"]["sessionId"] == root_session_id
    assert payload["sessionId"] == root_session_id
    assert payload["taskId"] == "root-task-http"
    assert payload["turnId"] == "root-turn-http"
    assert payload["sessionAnchorDegraded"] is False
    assert [item["candidateId"] for item in payload["scopedSessions"]] == [
        "H2",
        "H1",
    ]
    assert payload["scopedSessions"][0]["selectionId"] == "selection-http"
    assert payload["scopedSessions"][0]["parentSessionId"] == root_session_id
    assert payload["scopedSessions"][0]["rootSessionId"] == root_session_id
    assert payload["scopedSessions"][0]["fragmentRefs"] == [
        "hypothesis_fragment:h2"
    ]
    assert payload["scopedSessions"][1]["fragmentRefs"] == [
        "hypothesis_fragment:h1"
    ]


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


def test_research_runtime_budget_projects_canonical_receipt_usage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_id = "run-http-budget"
    node_run_id = "nr-http-budget-source-finding-1"
    limits = {
        "tokens": 2_000_000,
        "toolCalls": 600,
        "seconds": 14_400,
        "retries": 3,
    }
    reserved = {
        "estimatedTokens": 250_000,
        "tokens": 250_000,
        "toolCalls": 30,
        "seconds": 900,
        "retries": 1,
    }
    actual = {
        "inputTokens": 150,
        "cachedInputTokens": 100,
        "uncachedInputTokens": 50,
        "outputTokens": 25,
        "tokens": 175,
        "toolCalls": 7,
        "wallClockSeconds": 181,
    }

    with ledger_http_client(tmp_path, monkeypatch) as (client, runtime):
        run = build_run_record(run_id=run_id, status="running", last_event_sequence=1)

        def seed(uow) -> None:
            uow.repository.insert_run(run)
            uow.repository.insert_event(
                build_event_record(
                    sequence=1,
                    run_id=run_id,
                    event_id=f"evt-created-{run_id}",
                )
            )
            uow.repository.insert_command(
                build_command_record(
                    command_id="cmd-http-budget-1",
                    run_id=run_id,
                    node_id="source_finding",
                    idempotency_key="seed-http-budget-1",
                )
            )
            uow.repository.insert_attempt(
                build_attempt_record(
                    node_run_id=node_run_id,
                    run_id=run_id,
                    node_id="source_finding",
                    status="succeeded",
                    command_id="cmd-http-budget-1",
                )
            )
            uow.repository.insert_budget_receipt(
                receipt_id="budget-receipt-http-1",
                run_id=run_id,
                node_run_id=node_run_id,
                reservation_id="reservation-http-1",
                stage_id="knowledge_collection",
                policy_hash="policy-http-1",
                reserved_json=json.dumps({"reserved": reserved, "limits": limits}),
                created_at_ms=FIXED_NOW_MS,
            )
            uow.repository.update_budget_receipt(
                "budget-receipt-http-1",
                status="settled",
                now_ms=FIXED_NOW_MS + 181_000,
                settled_json=json.dumps({"usage": actual}),
            )

        runtime.store.submit(seed, force_flush=True).result(timeout=10)
        response = client.get(
            f"/api/research/workflow-runs/{run_id}/budget",
            params={"teamId": "research-team"},
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload["budgetLedgers"]) == 1
    ledger = payload["budgetLedgers"][0]
    assert ledger["stageId"] == "knowledge_collection"
    assert ledger["limits"] == {
        "tokens": 2_000_000,
        "toolCalls": 600,
        "wallClockSeconds": 14_400,
        "maxRetries": 3,
    }
    assert ledger["reserved"] == {
        "tokens": 0,
        "toolCalls": 0,
        "wallClockSeconds": 0,
        "maxRetries": 0,
    }
    assert ledger["consumed"] == {
        "tokens": 175,
        "toolCalls": 7,
        "wallClockSeconds": 181,
        "maxRetries": 0,
    }

    assert len(payload["budgetReservations"]) == 1
    reservation = payload["budgetReservations"][0]
    assert reservation["reservationId"] == "reservation-http-1"
    assert reservation["requested"] == {
        "tokens": 250_000,
        "toolCalls": 30,
        "wallClockSeconds": 900,
        "maxRetries": 1,
    }
    assert reservation["actual"] == actual
    assert reservation["status"] == "settled"
