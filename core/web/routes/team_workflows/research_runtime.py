"""Thin HTTP routes for research workflow runtime (ADR 0006)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    FormalReadRuntimeUnavailable,
    get_event_replay_service,
    get_event_stream_service,
    get_query_service,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    current_server_operator,
    server_operator_scope_from_http,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    RunNotFoundError as QueryRunNotFoundError,
    TeamScopeMismatchError as QueryTeamScopeMismatchError,
    WorkflowLedgerUnavailable,
    WorkflowQueryError,
)
from core.web.services.team_workflow.research_runtime.event_stream_service import (
    InvalidLastEventIdError,
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


class ResearchRunSafetyLimitsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stageTokens: dict[str, int]
    toolCalls: int = Field(..., ge=1)
    wallClockSeconds: int = Field(..., ge=1)
    maxRetries: int = Field(..., ge=1)


class CreateRunPayload(TeamScopedPayload):
    model_config = ConfigDict(extra="forbid")

    questionId: str = Field(..., min_length=1)
    safetyLimits: ResearchRunSafetyLimitsPayload
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
    if code == "command_forbidden":
        status = 403
    elif code.startswith("unknown") or code in {
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
        "research_project_question_mismatch",
        "challenge_question_not_launchable",
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
        "workflow_ledger_unavailable",
    }:
        status = 503
    else:
        status = 422
    return HTTPException(status_code=status, detail={"code": code, "message": str(exc)})


def _map_query_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FormalReadRuntimeUnavailable):
        return HTTPException(
            status_code=503,
            detail={"code": "workflow_ledger_unavailable", "message": str(exc)},
        )
    if isinstance(exc, WorkflowLedgerUnavailable):
        return HTTPException(
            status_code=503,
            detail={"code": "workflow_ledger_unavailable", "message": str(exc)},
        )
    if isinstance(exc, (QueryTeamScopeMismatchError, QueryRunNotFoundError)):
        return HTTPException(
            status_code=404,
            detail={"code": getattr(exc, "code", "run_not_found"), "message": str(exc)},
        )
    if isinstance(exc, InvalidLastEventIdError):
        return HTTPException(
            status_code=422,
            detail={"code": "invalid_event_cursor", "message": str(exc)},
        )
    if isinstance(exc, WorkflowQueryError):
        status = 404 if exc.code in {"team_scope_mismatch", "run_not_found"} else 422
        return HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=500,
        detail={"code": "workflow_query_error", "message": str(exc)},
    )



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


@router.get("/research/workflows/{workflow_id}/launch-options")
def research_workflow_launch_options(
    workflow_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return _svc().get_question_launch_options(
            workflow_id,
            team_id=_canonical_team_id(team_id),
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


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
        return _svc().create_question_run(
            workflow_id,
            team_id=payload.teamId,
            question_id=payload.questionId,
            safety_limits=payload.safetyLimits.model_dump(),
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


@router.get("/research/workflow-runs/{run_id}/snapshot")
def research_workflow_run_snapshot(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        snapshot = get_query_service().get_snapshot(
            team_id=_canonical_team_id(team_id),
            run_id=run_id,
        )
        return snapshot.to_dict()
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/nodes/{node_id}")
def research_workflow_node_detail(
    run_id: str,
    node_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return get_query_service().get_node_detail(
            team_id=_canonical_team_id(team_id),
            run_id=run_id,
            node_id=node_id,
        )
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/events")
def research_workflow_events(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    after_sequence: int = Query(0, alias="afterSequence"),
    limit: int = Query(500, ge=1, le=2000),
) -> dict:
    try:
        page = get_event_replay_service().list_events(
            team_id=_canonical_team_id(team_id),
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
        return page.to_dict()
    except FormalReadRuntimeUnavailable:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "workflow_ledger_unavailable",
                "message": "formal workflow event replay requires Workflow Ledger",
            },
        )
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get("/research/workflow-runs/{run_id}/stream")
def research_workflow_event_stream(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    after_sequence: int | None = Query(None, alias="afterSequence"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    scoped = _canonical_team_id(team_id)
    try:
        stream = get_event_stream_service()
        # Validate cursor/scope without materializing the full replay.
        stream.validate_stream_request(
            team_id=scoped,
            run_id=run_id,
            after_sequence=after_sequence,
            last_event_id=last_event_id,
        )
    except FormalReadRuntimeUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "workflow_ledger_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise _map_query_error(exc) from exc

    return StreamingResponse(
        stream.iter_sse(
            team_id=scoped,
            run_id=run_id,
            after_sequence=after_sequence,
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
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            return _svc().cancel_task_bundle(
                run_id,
                bundle_id,
                reason=payload.reason,
                idempotency_key=payload.idempotencyKey,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/task-bundles/reconcile")
def research_workflow_reconcile_task_bundles(
    run_id: str,
    payload: VersionedCommandPayload,
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            return _svc().reconcile_task_bundles(run_id)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/commands")
def research_workflow_command(
    run_id: str,
    payload: CommandPayload,
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            return _svc().apply_command(
                run_id,
                payload.command,
                idempotency_key=payload.idempotencyKey,
                payload=payload.payload,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve")
def research_workflow_human_resolve(
    run_id: str,
    task_id: str,
    payload: HumanTaskResolvePayload,
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            operator = current_server_operator()
            resolved_by = (
                str(operator.operator_id).strip() if operator is not None else ""
            ) or "operator"
            return _svc().resolve_human_task(
                run_id,
                task_id,
                decision=payload.decision,
                resolved_by=resolved_by,
                idempotency_key=payload.idempotencyKey,
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post("/research/workflow-runs/{run_id}/nodes/{node_id}/commands")
def research_workflow_node_command(
    run_id: str,
    node_id: str,
    payload: NodeCommandPayload,
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            return _svc().apply_node_command(
                run_id,
                node_id,
                payload.command,
                payload=_node_command_body(payload),
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.put("/research/workflow-runs/{run_id}/nodes/{node_id}/session-binding")
def research_workflow_session_binding(
    run_id: str,
    node_id: str,
    payload: SessionBindingPayload,
    request: Request,
) -> dict:
    _authorize_run(
        run_id,
        payload.teamId,
        expected_run_version=payload.expectedRunVersion,
    )
    try:
        with server_operator_scope_from_http(request):
            return _svc().put_session_binding(
                run_id,
                node_id,
                payload.model_dump(
                    exclude={"teamId", "expectedRunVersion"},
                ),
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc
