"""Thin HTTP routes for research workflow runtime (ADR 0006)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from core.web.services.team_workflow.research_runtime.event_stream import (
    iter_workflow_sse,
    parse_last_event_id,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    get_research_workflow_runtime_service,
)

from ._router import router


class TeamScopedPayload(BaseModel):
    teamId: str = Field(..., min_length=1)

    @field_validator("teamId")
    @classmethod
    def normalize_team_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("teamId must not be blank")
        return normalized


class CreateRunPayload(TeamScopedPayload):
    projectId: str = Field(..., min_length=1)
    questionId: str = Field(..., min_length=1)
    researchBriefHash: str = Field(..., min_length=1)
    datasetRefs: list[str]
    metricContract: dict[str, Any]
    constraintSnapshot: dict[str, Any]
    competitionRuleRef: str = Field(..., min_length=1)
    competitionRuleVersion: str = Field(..., min_length=1)
    trackAndRubricSnapshot: dict[str, Any]
    researchObjectiveContract: dict[str, Any]
    sourcePolicy: dict[str, Any]
    budgetPolicy: dict[str, Any]
    stopPolicy: dict[str, Any]
    environmentSnapshotRef: str = Field(..., min_length=1)
    modelRoutingPolicy: dict[str, Any]
    evaluationContract: dict[str, Any]
    idempotencyKey: str = Field(..., min_length=1)


class VersionedCommandPayload(TeamScopedPayload):
    idempotencyKey: str = Field(..., min_length=1)
    expectedRunVersion: int = Field(..., ge=1)


class HumanTaskResolvePayload(VersionedCommandPayload):
    decision: Literal["accept", "reject", "revise"]


class TaskBundleCancelPayload(VersionedCommandPayload):
    reason: str = Field(..., min_length=1)


class CommandPayload(VersionedCommandPayload):
    command: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionBindingPayload(VersionedCommandPayload):
    sessionId: str = ""
    taskId: str = ""
    turnId: str = ""
    agentId: str = ""
    roleKey: str = ""
    nodeRunId: str = ""
    nodeAttempt: int = 1
    sessionAttempt: int = 1
    checkpointId: str = ""
    supersedesBindingId: str = ""


class AgentBindingConfigPayload(TeamScopedPayload):
    workflowDefaults: dict[str, str] = Field(default_factory=dict)
    stageOverrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    nodeOverrides: dict[str, str] = Field(default_factory=dict)


class NodeCommandPayload(VersionedCommandPayload):
    command: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


def _svc():
    return get_research_workflow_runtime_service()


def _canonical_team_id(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail={"code": "team_id_required", "message": "teamId must not be blank"},
        )
    return normalized


def _map_error(exc: ResearchWorkflowError) -> HTTPException:
    code = exc.code
    if code.startswith("unknown") or code in {
        "team_scope_mismatch",
        "handoff_not_found",
        "task_not_found",
        "node_not_scheduled",
    }:
        status = 404
    elif code in {
        "run_version_conflict",
        "idempotency_conflict",
        "lease_owner_mismatch",
        "invalid_node_state",
        "invalid_human_task_state",
        "command_not_allowed_for_node",
    }:
        status = 409
    elif code in {
        "run_version_missing",
        "required_artifact_missing",
        "checkpoint_missing",
        "input_snapshot_missing",
        "smoke_evidence_missing",
    }:
        status = 412
    elif "budget" in code and ("exhaust" in code or "limit" in code):
        status = 429
    elif code in {
        "research_ledger_source_failed",
        "runtime_unavailable",
        "checkpointer_unavailable",
        "agent_task_service_unavailable",
    }:
        status = 503
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _authorize_run(
    run_id: str,
    team_id: str,
    *,
    expected_run_version: int | None = None,
) -> dict[str, Any]:
    try:
        return _svc().authorize_run_access(
            run_id,
            team_id=_canonical_team_id(team_id),
            expected_run_version=expected_run_version,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


def _node_command_body(payload: NodeCommandPayload) -> dict[str, Any]:
    body = dict(payload.payload)
    nested_key = str(body.get("idempotencyKey") or "").strip()
    if nested_key and nested_key != payload.idempotencyKey:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_conflict",
                "message": "payload idempotencyKey conflicts with command idempotencyKey",
            },
        )
    body["idempotencyKey"] = payload.idempotencyKey
    return body


@router.get("/research/workflows/{workflow_id}/definition")
def research_workflow_definition(workflow_id: str) -> dict:
    try:
        return _svc().get_definition(workflow_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflows/{workflow_id}/runs")
def research_workflow_runs(
    workflow_id: str,
    # teamId is the only public team scope. Legacy team_id is intentionally
    # rejected by FastAPI's required-field validation instead of ignored.
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return _svc().list_runs(workflow_id, team_id=_canonical_team_id(team_id))


@router.get("/research/workflows/{workflow_id}/agent-bindings/effective")
def research_workflow_effective_bindings(
    workflow_id: str,
    # Keep the canonical camel-case contract identical to the runs endpoint.
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return _svc().get_effective_agent_bindings(workflow_id, team_id=_canonical_team_id(team_id))
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.put("/research/workflows/{workflow_id}/agent-bindings")
def research_workflow_put_binding_config(
    workflow_id: str,
    payload: AgentBindingConfigPayload,
) -> dict:
    try:
        return _svc().put_agent_binding_config(
            workflow_id,
            payload.model_dump(),
            team_id=payload.teamId,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflows/{workflow_id}/runs", status_code=201)
def research_workflow_create_run(workflow_id: str, payload: CreateRunPayload) -> dict:
    try:
        return _svc().create_run(
            workflow_id,
            run_input={
                **payload.model_dump(exclude={"idempotencyKey"}),
                "createdBy": "operator",
            },
            idempotency_key=payload.idempotencyKey,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}")
def research_workflow_run(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return _authorize_run(run_id, team_id)


@router.get("/research/workflow-runs/{run_id}/canvas")
def research_workflow_run_canvas(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().get_canvas_projection(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/nodes/{node_id}")
def research_workflow_node_detail(
    run_id: str,
    node_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().get_node_detail(run_id, node_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/events")
def research_workflow_events(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    after_sequence: int = Query(0, alias="afterSequence"),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().list_events(run_id, after_sequence=after_sequence)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/stream")
def research_workflow_event_stream(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    try:
        parse_last_event_id(last_event_id)
        _authorize_run(run_id, team_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_event_cursor", "message": str(exc)},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc
    return StreamingResponse(
        iter_workflow_sse(
            lambda: _svc().authorize_run_access(run_id, team_id=team_id),
            last_event_id=last_event_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/research/workflow-runs/{run_id}/handoffs")
def research_workflow_handoffs(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().list_handoffs(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/research-ledger")
def research_workflow_research_ledger(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().get_research_ledger(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/budget")
def research_workflow_budget(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    return _svc().get_budget(run_id)


@router.get("/research/workflow-runs/{run_id}/hypotheses")
def research_workflow_hypotheses(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    return _svc().get_hypotheses(run_id)


@router.get("/research/workflow-runs/{run_id}/experiment-campaigns")
def research_workflow_experiment_campaigns(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    return _svc().get_experiment_campaigns(run_id)


@router.get("/research/workflow-runs/{run_id}/evaluation")
def research_workflow_evaluation(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    return _svc().get_evaluation(run_id)


@router.get("/research/workflow-runs/{run_id}/handoffs/{handoff_id}")
def research_workflow_handoff_detail(
    run_id: str,
    handoff_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    _authorize_run(run_id, team_id)
    try:
        return _svc().get_handoff_detail(run_id, handoff_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/task-bundles/{bundle_id}/cancel")
def research_workflow_cancel_task_bundle(
    run_id: str,
    bundle_id: str,
    payload: TaskBundleCancelPayload,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().cancel_task_bundle(
            run_id,
            bundle_id,
            reason=payload.reason,
            idempotency_key=payload.idempotencyKey,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/task-bundles/reconcile")
def research_workflow_reconcile_task_bundles(
    run_id: str,
    payload: VersionedCommandPayload,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().reconcile_task_bundles(run_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/commands")
def research_workflow_command(run_id: str, payload: CommandPayload) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().apply_command(
            run_id,
            payload.command,
            idempotency_key=payload.idempotencyKey,
            payload=payload.payload,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve")
def research_workflow_human_resolve(run_id: str, task_id: str, payload: HumanTaskResolvePayload) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().resolve_human_task(
            run_id,
            task_id,
            decision=payload.decision,
            resolved_by="operator",
            idempotency_key=payload.idempotencyKey,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/nodes/{node_id}/commands")
def research_workflow_node_command(run_id: str, node_id: str, payload: NodeCommandPayload) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().apply_node_command(
            run_id,
            node_id,
            payload.command,
            payload=_node_command_body(payload),
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.put("/research/workflow-runs/{run_id}/nodes/{node_id}/session-binding")
def research_workflow_session_binding(run_id: str, node_id: str, payload: SessionBindingPayload) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        return _svc().put_session_binding(
            run_id,
            node_id,
            payload.model_dump(
                exclude={"teamId", "expectedRunVersion"},
            ),
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc
