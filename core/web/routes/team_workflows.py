"""Team workflow orchestration API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import (
    DEFAULT_OWNER_AGENT_ID,
    WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
    TeamWorkflowOrchestrationError,
    build_candidate_graph,
    decide_transfer_request,
    ensure_team_workflow_orchestration,
    get_team_workflow_orchestration,
    build_local_research_model_task,
    invoke_local_research_model,
    list_candidate_store,
    record_local_research_model_output,
    register_candidate_source,
    submit_transfer_request,
    validate_candidate_store,
)


router = APIRouter(tags=["team-workflows"])


class WorkflowEnsurePayload(BaseModel):
    workflowKind: str = Field(WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH, max_length=80)
    ownerAgentId: str = Field(DEFAULT_OWNER_AGENT_ID, max_length=160)


class CandidateSourcePayload(BaseModel):
    candidateType: str = Field("source_manifest", max_length=80)
    title: str = Field("", max_length=240)
    sourceUrl: str = Field("", max_length=2000)
    sourcePath: str = Field("", max_length=2000)
    sourceKind: str = Field("", max_length=80)
    sha256: str = Field("", max_length=128)
    allowedForAnalysis: bool | None = None
    pageScope: str = Field("", max_length=160)
    summary: str = Field("", max_length=4000)
    tags: list[str] = Field(default_factory=list, max_length=24)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    metadata: dict[str, Any] = Field(default_factory=dict)
    createdByAgent: str = Field("", max_length=160)


class TransferRequestPayload(BaseModel):
    candidateId: str = Field("", max_length=128)
    fromNode: str = Field("", max_length=120)
    toNode: str = Field("", max_length=120)
    requestedByAgent: str = Field("", max_length=160)
    reason: str = Field("", max_length=4000)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TransferDecisionPayload(BaseModel):
    decision: str = Field("approved", max_length=32)
    decidedByAgent: str = Field("", max_length=160)
    targetState: str = Field("", max_length=120)
    decisionNote: str = Field("", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocalResearchModelTaskPayload(BaseModel):
    taskType: str = Field("", max_length=80)
    modelId: str = Field("", max_length=160)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    candidateRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    excerpt: str = Field("", max_length=24000)
    createdByAgent: str = Field("", max_length=160)


class LocalResearchModelOutputPayload(BaseModel):
    taskType: str = Field("", max_length=80)
    modelId: str = Field("", max_length=160)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    output: dict[str, Any] = Field(default_factory=dict)
    createdByAgent: str = Field("", max_length=160)


class LocalResearchModelInvokePayload(LocalResearchModelTaskPayload):
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)


class CandidateGraphBuildPayload(BaseModel):
    title: str = Field("", max_length=240)
    createdByAgent: str = Field("", max_length=160)


@router.get("/teams/{team_id}/workflow-orchestration")
def team_workflow_detail(team_id: str) -> dict:
    try:
        return get_team_workflow_orchestration(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/teams/{team_id}/workflow-orchestration")
def team_workflow_ensure(team_id: str, payload: WorkflowEnsurePayload) -> dict:
    try:
        return ensure_team_workflow_orchestration(
            team_id,
            workflow_kind=payload.workflowKind,
            owner_agent_id=payload.ownerAgentId,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/candidates/source", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_source_create(team_id: str, payload: CandidateSourcePayload) -> dict:
    try:
        return register_candidate_source(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/workflow-orchestration/candidates")
def team_workflow_candidate_list(
    team_id: str,
    candidateType: str = "",
    currentState: str = "",
    qualityStatus: str = "",
    limit: int = 100,
) -> dict:
    try:
        return list_candidate_store(
            team_id,
            candidate_type=candidateType,
            current_state=currentState,
            quality_status=qualityStatus,
            limit=limit,
        )
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/workflow-orchestration/candidates/validation")
def team_workflow_candidate_validation(team_id: str) -> dict:
    try:
        return validate_candidate_store(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/candidate-graph", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_graph_build(team_id: str, payload: CandidateGraphBuildPayload) -> dict:
    try:
        return build_candidate_graph(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/transfers", status_code=status.HTTP_201_CREATED)
def team_workflow_transfer_create(team_id: str, payload: TransferRequestPayload) -> dict:
    try:
        return submit_transfer_request(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/transfers/{transfer_id}/decide")
def team_workflow_transfer_decide(team_id: str, transfer_id: str, payload: TransferDecisionPayload) -> dict:
    try:
        return decide_transfer_request(team_id, transfer_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/tasks", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_task_create(team_id: str, payload: LocalResearchModelTaskPayload) -> dict:
    try:
        return build_local_research_model_task(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/outputs", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_output_create(team_id: str, payload: LocalResearchModelOutputPayload) -> dict:
    try:
        return record_local_research_model_output(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/invoke", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_invoke(team_id: str, payload: LocalResearchModelInvokePayload) -> dict:
    try:
        return invoke_local_research_model(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
