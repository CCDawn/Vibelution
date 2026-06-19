"""Template-driven Research Loop API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.research_loop_service import (
    ResearchLoopError,
    create_research_loop,
    get_research_loop_status,
    list_research_loop_templates,
    record_research_loop_decision,
    record_research_loop_evidence,
)
from core.web.services.team_service import TeamNotFoundError, TeamServiceError


router = APIRouter(tags=["research-loop"])


class ResearchLoopCreatePayload(BaseModel):
    templateId: str = Field("algorithm_model_experiment", max_length=96)
    title: str = Field("", max_length=240)
    researchQuestion: str = Field("", max_length=2000)
    stageRoundId: str = Field("", max_length=128)
    planId: str = Field("", max_length=128)
    targetRef: str = Field("", max_length=500)
    candidateIds: list[str] = Field(default_factory=list, max_length=24)
    inputRefs: list[str] = Field(default_factory=list, max_length=80)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    datasetRefs: list[str] = Field(default_factory=list, max_length=24)
    environmentRefs: list[str] = Field(default_factory=list, max_length=24)
    constraints: str = Field("", max_length=4000)
    createdByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopEvidencePayload(BaseModel):
    evidenceType: str = Field("", max_length=96)
    status: str = Field("needs_review", max_length=64)
    summary: str = Field("", max_length=4000)
    metricName: str = Field("", max_length=500)
    metricValue: str = Field("", max_length=240)
    baselineMetricValue: str = Field("", max_length=240)
    delta: str = Field("", max_length=240)
    artifactRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    datasetRefs: list[str] = Field(default_factory=list, max_length=24)
    environmentRefs: list[str] = Field(default_factory=list, max_length=24)
    logRefs: list[str] = Field(default_factory=list, max_length=24)
    commandPreview: str = Field("", max_length=2000)
    recordedByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResearchLoopDecisionPayload(BaseModel):
    decision: str = Field("", max_length=96)
    rationale: str = Field("", max_length=4000)
    nextTemplateId: str = Field("", max_length=96)
    nextActions: list[str] = Field(default_factory=list, max_length=24)
    decidedByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/teams/{team_id}/workflow-orchestration/research-loop/templates")
def team_research_loop_templates(team_id: str) -> dict:
    try:
        get_research_loop_status(team_id)
        return list_research_loop_templates()
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/workflow-orchestration/research-loop/status")
def team_research_loop_status(team_id: str) -> dict:
    try:
        return get_research_loop_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/research-loop/loops", status_code=status.HTTP_201_CREATED)
def team_research_loop_create(team_id: str, payload: ResearchLoopCreatePayload) -> dict:
    try:
        return create_research_loop(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop_id}/evidence",
    status_code=status.HTTP_201_CREATED,
)
def team_research_loop_evidence_record(team_id: str, loop_id: str, payload: ResearchLoopEvidencePayload) -> dict:
    try:
        return record_research_loop_evidence(team_id, loop_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop_id}/decision",
    status_code=status.HTTP_201_CREATED,
)
def team_research_loop_decision_record(team_id: str, loop_id: str, payload: ResearchLoopDecisionPayload) -> dict:
    try:
        return record_research_loop_decision(team_id, loop_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
