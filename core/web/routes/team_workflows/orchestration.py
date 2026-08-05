"""Team workflow routes: orchestration."""
from __future__ import annotations
from fastapi import Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router

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
        _raise_team_workflow_route_error("workflow.ensure", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "workflow.ensure",
            team_id,
            exc,
            status_code=422,
            fields={"workflowKind": payload.workflowKind, "ownerAgentId": payload.ownerAgentId},
        )
