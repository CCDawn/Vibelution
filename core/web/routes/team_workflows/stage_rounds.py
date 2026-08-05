"""Team workflow routes: stage_rounds."""
from __future__ import annotations
from fastapi import Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router

@router.get("/teams/{team_id}/workflow-orchestration/stage-rounds/status")
def team_workflow_research_stage_round_status(team_id: str) -> dict:
    try:
        return get_research_stage_round_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/stage-rounds/start", status_code=status.HTTP_201_CREATED)
def team_workflow_research_stage_round_start(team_id: str, payload: ResearchStageRoundStartPayload) -> dict:
    try:
        return start_research_stage_round(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.start",
            team_id,
            exc,
            status_code=404,
            fields={"stageType": payload.stageType, "mode": payload.mode},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.start",
            team_id,
            exc,
            status_code=422,
            fields={"stageType": payload.stageType, "mode": payload.mode, "requestedByAgent": payload.requestedByAgent},
        )
