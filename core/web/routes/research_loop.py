"""Template-driven Research Loop API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from core.web.routes.research_loop_models import (
    ResearchLoopCreatePayload,
    ResearchLoopCreateResponse,
    ResearchLoopDecisionPayload,
    ResearchLoopDecisionResponse,
    ResearchLoopEvidencePayload,
    ResearchLoopEvidenceResponse,
    ResearchLoopIterationDesignPayload,
    ResearchLoopStatusResponse,
    ResearchLoopTemplatesResponse,
)
from core.web.services.research_loop_service import (
    ResearchLoopError,
    create_research_loop,
    get_research_loop_status,
    list_research_loop_templates,
    materialize_research_loop_iteration_design,
    record_research_loop_decision,
    record_research_loop_evidence,
)
from core.web.services.team_service import TeamNotFoundError, TeamServiceError


router = APIRouter(tags=["research-loop"])


@router.get(
    "/teams/{team_id}/workflow-orchestration/research-loop/templates",
    response_model=ResearchLoopTemplatesResponse,
    response_model_exclude_unset=True,
)
def team_research_loop_templates(team_id: str) -> dict:
    try:
        get_research_loop_status(team_id)
        return list_research_loop_templates()
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/teams/{team_id}/workflow-orchestration/research-loop/status",
    response_model=ResearchLoopStatusResponse,
    response_model_exclude_unset=True,
)
def team_research_loop_status(team_id: str) -> dict:
    try:
        return get_research_loop_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-loop/loops",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchLoopCreateResponse,
    response_model_exclude_unset=True,
)
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
    response_model=ResearchLoopEvidenceResponse,
    response_model_exclude_unset=True,
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
    response_model=ResearchLoopDecisionResponse,
    response_model_exclude_unset=True,
)
def team_research_loop_decision_record(team_id: str, loop_id: str, payload: ResearchLoopDecisionPayload) -> dict:
    try:
        return record_research_loop_decision(team_id, loop_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-loop/loops/{loop_id}/proposals/{proposal_id}/design-draft",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchLoopDecisionResponse,
    response_model_exclude_unset=True,
)
def team_research_loop_iteration_design_materialize(
    team_id: str,
    loop_id: str,
    proposal_id: str,
    payload: ResearchLoopIterationDesignPayload,
) -> dict:
    try:
        return materialize_research_loop_iteration_design(team_id, loop_id, proposal_id, payload.model_dump())
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, ResearchLoopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
