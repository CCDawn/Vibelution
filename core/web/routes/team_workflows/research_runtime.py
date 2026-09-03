"""Thin HTTP routes for research workflow runtime (ADR 0006)."""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from core.research.workflow.contracts import (
    ActorRef,
    CommandRequest,
    WorkflowCommandKind,
)
from core.research.workflow.ledger.errors import (
    CommandNotAllowedError,
    IdempotencyConflictError,
    RunVersionConflictError,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    CommandForbiddenError,
    HumanTaskNotFoundError,
    InvalidHumanTaskStateError,
    KnowledgeCommandError,
    NodeNotReadyError,
    WorkflowCommandError,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    RunNotFoundError as CommandRunNotFoundError,
)
from core.web.services.team_workflow.research_runtime.command_service import (
    TeamScopeMismatchError as CommandTeamScopeMismatchError,
)
from core.web.services.team_workflow.research_runtime.event_stream_service import (
    InvalidLastEventIdError,
)
from core.web.services.team_workflow.research_runtime.formal_read_runtime import (
    FormalReadRuntimeUnavailable,
    get_event_replay_service,
    get_event_stream_service,
    get_query_service,
)
from core.web.services.team_workflow.research_runtime.formal_write_runtime import (
    FormalWriteRuntimeUnavailable,
    WorkflowMigrationRequired,
    get_command_service,
)
from core.web.services.team_workflow.research_runtime.ids import new_id
from core.web.services.team_workflow.research_runtime.ledger_domain_projections import (
    HandoffQueryError,
    project_budget_from_snapshot,
    project_campaigns_from_snapshot,
    project_evaluation_from_snapshot,
    project_handoff_detail,
    project_handoffs,
    project_hypotheses_from_snapshot,
    project_research_ledger_from_snapshot,
)
from core.web.services.team_workflow.research_runtime.operator_authorization import (
    current_server_operator,
    server_operator_scope_from_http,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    RunNotFoundError as QueryRunNotFoundError,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    TeamScopeMismatchError as QueryTeamScopeMismatchError,
)
from core.web.services.team_workflow.research_runtime.query_service import (
    WorkflowLedgerUnavailable,
    WorkflowQueryError,
)
from core.web.services.team_workflow.research_runtime.question_lineage_service import (
    project_question_lineage,
)
from core.web.services.team_workflow.research_runtime.run_creation import (
    create_question_run,
)
from core.web.services.team_workflow.research_runtime.service import (
    ResearchWorkflowError,
    get_research_workflow_runtime_service,
)

from ._router import router
from .research_runtime_models import (
    ResearchWorkflowBindingConfigResponse,
    ResearchWorkflowBudgetResponse,
    ResearchWorkflowCampaignListResponse,
    ResearchWorkflowCommandReceiptResponse,
    ResearchWorkflowCreateRunResponse,
    ResearchWorkflowDefinitionResponse,
    ResearchWorkflowEffectiveBindingsResponse,
    ResearchWorkflowEvaluationResponse,
    ResearchWorkflowEventPageResponse,
    ResearchWorkflowExperimentActivationResponse,
    ResearchWorkflowHandoffDetailResponse,
    ResearchWorkflowHandoffListResponse,
    ResearchWorkflowHypothesisListResponse,
    ResearchWorkflowLaunchOptionsResponse,
    ResearchWorkflowLedgerResponse,
    ResearchWorkflowNodeDetailResponse,
    ResearchWorkflowQuestionLineageResponse,
    ResearchWorkflowRunListResponse,
    ResearchWorkflowRunSnapshotResponse,
)


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


class ActivateExperimentPayload(TeamScopedPayload):
    model_config = ConfigDict(extra="forbid")

    confirmed: StrictBool = False


class VersionedCommandPayload(TeamScopedPayload):
    idempotencyKey: str = Field(..., min_length=1)
    expectedRunVersion: int = Field(..., ge=1)


class CommandPayload(VersionedCommandPayload):
    command: str = Field(..., min_length=1)
    nodeId: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class StageOneCommandPayload(VersionedCommandPayload):
    """Stage-one G1 closeout operator commands (Challenge Program flow).

    The two system commands execute synchronously through
    ``apply_node_command``; the closure node defaults to the run's
    ``inputSnapshot.stageOneCompletionPolicy.closureNodeId`` so callers never
    hard-code the workflow shape.
    """

    command: Literal["build_stage_one_package", "finalize_stage_one"]
    nodeId: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class KnowledgeSearchEnvelopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list, max_length=32)
    evidenceTypes: list[str] = Field(default_factory=list, max_length=32)
    timeWindow: dict[str, Any] = Field(default_factory=dict)


class KnowledgeCollectionPayload(VersionedCommandPayload):
    """ensure_knowledge_collection payload (knowledge sideflow facade).

    ``searchEnvelope`` (keywords / evidenceTypes / timeWindow) and
    ``requirements`` map into the invocation envelope fingerprints, so a
    changed request is a NEW invocation while an identical request replays
    the same one.  ``managedSourceRootIds`` joins the scope fingerprint and
    is passed through to the collection chain.
    """

    model_config = ConfigDict(extra="forbid")

    questionId: str = Field(..., min_length=1)
    nodeId: str | None = None
    searchEnvelope: KnowledgeSearchEnvelopePayload = Field(
        default_factory=KnowledgeSearchEnvelopePayload
    )
    requirements: dict[str, Any] = Field(default_factory=dict)
    sourcePolicyVersion: str = "1"
    managedSourceRootIds: list[str] = Field(default_factory=list, max_length=32)
    parentNodeRunId: str = ""
    parentAttempt: int = Field(default=1, ge=1)


class AgentBindingConfigPayload(TeamScopedPayload):
    stageOverrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    nodeOverrides: dict[str, str] = Field(default_factory=dict)


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
        "deep_experiment_not_found",
    }:
        status = 404
    elif code in {
        "run_version_conflict",
        "idempotency_conflict",
        "definition_resolution_degraded",
        "lease_owner_mismatch",
        "invalid_node_state",
        "invalid_human_task_state",
        "command_not_allowed_for_node",
        "research_project_question_mismatch",
        "challenge_question_not_launchable",
        "deep_experiment_campaign_not_activated",
        "experiment_activation_not_allowed",
        "campaign_theme_mismatch",
        "dev_theme_not_activatable",
        "stage_one_package_not_ready",
        "stage_one_program_review_not_approved",
        "stage_one_result_package_missing",
    }:
        status = 409
    elif code in {
        "experiment_activation_confirmation_required",
        "invalid_safety_limits",
    }:
        status = 422
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
    if isinstance(exc, (FormalReadRuntimeUnavailable, FormalWriteRuntimeUnavailable, WorkflowLedgerUnavailable)):
        return HTTPException(
            status_code=503,
            detail={"code": "workflow_ledger_unavailable", "message": str(exc)},
        )
    if isinstance(exc, WorkflowMigrationRequired):
        return HTTPException(
            status_code=503,
            detail={"code": "workflow_migration_required", "message": str(exc)},
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
        status = (
            404
            if exc.code in {"team_scope_mismatch", "run_not_found", "unknown_node"}
            else 422
        )
        return HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": str(exc)},
        )
    return HTTPException(
        status_code=500,
        detail={"code": "workflow_query_error", "message": str(exc)},
    )


def _map_node_not_ready_error(exc: NodeNotReadyError) -> HTTPException:
    """Expose readiness blockers so a rejected retry is actionable in the UI."""
    readiness = getattr(exc, "readiness", None)
    blockers = []
    for blocker in getattr(readiness, "blockers", ()) or ():
        to_dict = getattr(blocker, "to_dict", None)
        if callable(to_dict):
            blockers.append(to_dict())
        elif isinstance(blocker, dict):
            blockers.append(dict(blocker))
        else:
            blockers.append({"detail": str(blocker)})
    return HTTPException(
        status_code=412,
        detail={
            "code": "node_not_ready",
            "message": str(exc),
            "blockers": blockers,
        },
    )


@router.get(
    "/research/workflows/{workflow_id}/definition",
    response_model=ResearchWorkflowDefinitionResponse,
    response_model_exclude_unset=True,
)
def research_workflow_definition(workflow_id: str) -> dict:
    try:
        return _svc().get_definition(workflow_id)
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get(
    "/research/workflows/{workflow_id}/runs",
    response_model=ResearchWorkflowRunListResponse,
    response_model_exclude_unset=True,
)
def research_workflow_runs(
    workflow_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return get_query_service().list_runs(
            team_id=_canonical_team_id(team_id),
            workflow_id=workflow_id,
        )
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get(
    "/research/workflows/{workflow_id}/launch-options",
    response_model=ResearchWorkflowLaunchOptionsResponse,
    response_model_exclude_unset=True,
)
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


@router.get(
    "/research/workflows/{workflow_id}/agent-bindings/effective",
    response_model=ResearchWorkflowEffectiveBindingsResponse,
    response_model_exclude_unset=True,
)
def research_workflow_effective_bindings(
    workflow_id: str,
    # Keep the canonical camel-case contract identical to the runs endpoint.
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return _svc().get_effective_agent_bindings(workflow_id, team_id=_canonical_team_id(team_id))
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.put(
    "/research/workflows/{workflow_id}/agent-bindings",
    response_model=ResearchWorkflowBindingConfigResponse,
    response_model_exclude_unset=True,
)
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


@router.post(
    "/research/workflows/{workflow_id}/runs",
    status_code=201,
    response_model=ResearchWorkflowCreateRunResponse,
    response_model_exclude_unset=True,
)
def research_workflow_create_run(workflow_id: str, payload: CreateRunPayload) -> dict:
    try:
        return create_question_run(
            workflow_id,
            team_id=payload.teamId,
            question_id=payload.questionId,
            safety_limits=payload.safetyLimits.model_dump(),
            idempotency_key=payload.idempotencyKey,
        )
    except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired) as exc:
        raise _map_query_error(exc) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.post(
    "/research/workflows/{workflow_id}/experiments/{experiment_id}/activate",
    response_model=ResearchWorkflowExperimentActivationResponse,
    response_model_exclude_unset=True,
)
def research_workflow_activate_experiment(
    workflow_id: str,
    experiment_id: str,
    payload: ActivateExperimentPayload,
) -> dict:
    try:
        return _svc().activate_experiment_campaign(
            workflow_id,
            team_id=payload.teamId,
            experiment_id=experiment_id,
            confirmed=payload.confirmed,
        )
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get(
    "/research/workflow-runs/{run_id}/snapshot",
    response_model=ResearchWorkflowRunSnapshotResponse,
    response_model_exclude_unset=True,
)
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


@router.get(
    "/research/workflow-runs/{run_id}/nodes/{node_id}",
    response_model=ResearchWorkflowNodeDetailResponse,
    response_model_exclude_unset=True,
)
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
        ).to_dict()
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get(
    "/research/workflow-runs/{run_id}/events",
    response_model=ResearchWorkflowEventPageResponse,
    response_model_exclude_unset=True,
)
def research_workflow_events(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    after_sequence: int = Query(0, alias="afterSequence", ge=0),
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


@router.get(
    "/research/workflow-runs/{run_id}/stream",
    response_class=StreamingResponse,
)
def research_workflow_event_stream(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    after_sequence: int | None = Query(None, alias="afterSequence", ge=0),
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


def _snapshot_or_raise(run_id: str, team_id: str):
    try:
        return get_query_service().get_snapshot(
            team_id=_canonical_team_id(team_id),
            run_id=run_id,
        )
    except Exception as exc:
        raise _map_query_error(exc) from exc


@router.get(
    "/research/workflow-runs/{run_id}/handoffs",
    response_model=ResearchWorkflowHandoffListResponse,
    response_model_exclude_unset=True,
)
def research_workflow_handoffs(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return project_handoffs(_snapshot_or_raise(run_id, team_id))


@router.get(
    "/research/workflow-runs/{run_id}/research-ledger",
    response_model=ResearchWorkflowLedgerResponse,
    response_model_exclude_unset=True,
)
def research_workflow_research_ledger(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return project_research_ledger_from_snapshot(_snapshot_or_raise(run_id, team_id))
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc


@router.get(
    "/research/workflow-runs/{run_id}/budget",
    response_model=ResearchWorkflowBudgetResponse,
    response_model_exclude_unset=True,
)
def research_workflow_budget(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return project_budget_from_snapshot(_snapshot_or_raise(run_id, team_id))


@router.get(
    "/research/workflow-runs/{run_id}/hypotheses",
    response_model=ResearchWorkflowHypothesisListResponse,
    response_model_exclude_unset=True,
)
def research_workflow_hypotheses(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return project_hypotheses_from_snapshot(_snapshot_or_raise(run_id, team_id))


@router.get(
    "/research/workflow-runs/{run_id}/experiment-campaigns",
    response_model=ResearchWorkflowCampaignListResponse,
    response_model_exclude_unset=True,
)
def research_workflow_experiment_campaigns(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return project_campaigns_from_snapshot(_snapshot_or_raise(run_id, team_id))


@router.get(
    "/research/workflow-runs/{run_id}/evaluation",
    response_model=ResearchWorkflowEvaluationResponse,
    response_model_exclude_unset=True,
)
def research_workflow_evaluation(
    run_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    return project_evaluation_from_snapshot(_snapshot_or_raise(run_id, team_id))


@router.get(
    "/research/workflow-runs/{run_id}/handoffs/{handoff_id}",
    response_model=ResearchWorkflowHandoffDetailResponse,
    response_model_exclude_unset=True,
)
def research_workflow_handoff_detail(
    run_id: str,
    handoff_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
) -> dict:
    try:
        return project_handoff_detail(_snapshot_or_raise(run_id, team_id), handoff_id)
    except HandoffQueryError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get(
    "/research/questions/{question_id}/lineage",
    response_model=ResearchWorkflowQuestionLineageResponse,
    response_model_exclude_unset=True,
)
def research_workflow_question_lineage(
    question_id: str,
    team_id: str = Query(..., alias="teamId", min_length=1),
    run_id: str = Query("", alias="runId"),
    round_id: str = Query("", alias="roundId"),
) -> dict:
    """Read-only single-question lineage projection (R4.5).

    The aggregator degrades per segment internally, so this thin route never
    maps data absence to an error — the panel labels the gap instead.
    """
    return project_question_lineage(
        team_id=_canonical_team_id(team_id),
        question_id=question_id,
        workflow_run_id=run_id,
        round_id=round_id,
    )


@router.post(
    "/research/workflow-runs/{run_id}/commands",
    status_code=202,
    response_model=ResearchWorkflowCommandReceiptResponse,
    response_model_exclude_unset=True,
)
def research_workflow_command(
    run_id: str,
    payload: CommandPayload,
    request: Request,
) -> dict:
    try:
        kind = WorkflowCommandKind(payload.command)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "unknown_command", "message": str(exc)},
        ) from exc
    return _submit_workflow_command(
        run_id=run_id,
        team_id=payload.teamId,
        kind=kind,
        node_id=payload.nodeId,
        expected_run_version=payload.expectedRunVersion,
        idempotency_key=payload.idempotencyKey,
        payload=dict(payload.payload or {}),
        request=request,
    )


@router.post(
    "/research/workflow-runs/{run_id}/knowledge-collection",
    status_code=202,
    response_model=ResearchWorkflowCommandReceiptResponse,
    response_model_exclude_unset=True,
)
def research_workflow_ensure_knowledge_collection(
    run_id: str,
    payload: KnowledgeCollectionPayload,
    request: Request,
) -> dict:
    """ensure_knowledge_collection facade: idempotent knowledge request.

    A repeated identical request returns the SAME invocation (and never a
    second child run); the receipt carries the invocation facts in
    ``result``.
    """
    return _submit_workflow_command(
        run_id=run_id,
        team_id=payload.teamId,
        kind=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
        node_id=payload.nodeId,
        expected_run_version=payload.expectedRunVersion,
        idempotency_key=payload.idempotencyKey,
        payload={
            "questionId": payload.questionId,
            "searchEnvelope": payload.searchEnvelope.model_dump(),
            "requirements": dict(payload.requirements or {}),
            "sourcePolicyVersion": payload.sourcePolicyVersion,
            "managedSourceRootIds": list(payload.managedSourceRootIds),
            "parentNodeRunId": payload.parentNodeRunId,
            "parentAttempt": payload.parentAttempt,
        },
        request=request,
    )


def _submit_workflow_command(
    *,
    run_id: str,
    team_id: str,
    kind: WorkflowCommandKind,
    node_id: str | None,
    expected_run_version: int,
    idempotency_key: str,
    payload: dict[str, Any],
    request: Request,
) -> dict:
    try:
        with server_operator_scope_from_http(request):
            operator = current_server_operator()
            actor_id = str(operator.operator_id).strip() if operator is not None else ""
            receipt = get_command_service().submit(
                CommandRequest(
                    command_id=new_id("cmd"),
                    run_id=run_id,
                    team_id=team_id,
                    command=kind,
                    node_id=(node_id or None),
                    expected_run_version=expected_run_version,
                    idempotency_key=idempotency_key,
                    payload=payload,
                    requested_by=ActorRef("user", actor_id or "operator"),
                    requested_at_ms=int(time.time() * 1000),
                )
            )
            return receipt.to_dict()
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except CommandForbiddenError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc)},
        ) from exc
    except (FormalWriteRuntimeUnavailable, WorkflowMigrationRequired) as exc:
        raise _map_query_error(exc) from exc
    except CommandRunNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "run_not_found", "message": str(exc)},
        ) from exc
    except KnowledgeCommandError as exc:
        status = {
            "unknown_parent_run": 404,
            "unknown_invocation": 404,
            "unknown_node": 404,
            "question_mismatch": 409,
        }.get(str(getattr(exc, "code", "") or ""), 422)
        raise HTTPException(
            status_code=status,
            detail={
                "code": str(getattr(exc, "code", "") or "knowledge_command_failed"),
                "message": str(exc),
            },
        ) from exc
    except CommandTeamScopeMismatchError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "team_scope_mismatch", "message": str(exc)},
        ) from exc
    except RunVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "run_version_conflict", "message": str(exc)},
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "idempotency_conflict", "message": str(exc)},
        ) from exc
    except CommandNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "command_not_allowed", "message": str(exc)},
        ) from exc
    except NodeNotReadyError as exc:
        raise _map_node_not_ready_error(exc) from exc
    except InvalidHumanTaskStateError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "invalid_human_task_state", "message": str(exc)},
        ) from exc
    except HumanTaskNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "task_not_found", "message": str(exc)},
        ) from exc
    except WorkflowCommandError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "unknown_command", "message": str(exc)},
        ) from exc


def _stage_one_closure_node_id(record: dict[str, Any], requested_node_id: str) -> str:
    """Resolve the closure node from the run's authoritative stage-one policy."""
    node_id = str(requested_node_id or "").strip()
    if node_id:
        return node_id
    snapshot = record.get("inputSnapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    policy = snapshot.get("stageOneCompletionPolicy")
    policy = policy if isinstance(policy, dict) else {}
    return str(policy.get("closureNodeId") or "").strip() or "hypothesis_design"


@router.post(
    "/research/workflow-runs/{run_id}/stage-one/commands",
)
def research_workflow_stage_one_command(
    run_id: str,
    payload: StageOneCommandPayload,
    request: Request,
) -> dict:
    """Stage-one G1 closeout facade over the runtime service (thin route).

    ``build_stage_one_package`` registers the Challenge Program result
    package; ``finalize_stage_one`` re-reads Program authority and promotes
    the pending closeout. All semantics stay in the system adapters.
    """
    try:
        with server_operator_scope_from_http(request):
            operator = current_server_operator()
            actor_id = (
                str(operator.operator_id).strip() if operator is not None else ""
            )
            service = _svc()
            record = service.get_run(run_id)
            if str(record.get("teamId") or "") != payload.teamId:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "team_scope_mismatch",
                        "message": "run does not belong to the requested team",
                    },
                )
            if int(record.get("runVersion") or 0) != payload.expectedRunVersion:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "run_version_conflict",
                        "message": "expectedRunVersion does not match the run",
                    },
                )
            return service.apply_node_command(
                run_id=run_id,
                node_id=_stage_one_closure_node_id(record, payload.nodeId),
                command=payload.command,
                payload={
                    **payload.payload,
                    "idempotencyKey": payload.idempotencyKey,
                    "requestedBy": actor_id or "operator",
                },
            )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "command_forbidden", "message": str(exc) or "command_forbidden"},
        ) from exc
    except ResearchWorkflowError as exc:
        raise _map_error(exc) from exc
