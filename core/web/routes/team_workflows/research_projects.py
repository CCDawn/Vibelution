"""Team workflow routes: research_projects."""
from __future__ import annotations
from fastapi import HTTPException, Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router

@router.get(
    "/teams/{team_id}/workflow-orchestration/research-projects",
    response_model=ResearchProjectListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_projects(team_id: str) -> dict:
    try:
        return list_research_projects(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error("research_project.list", team_id, exc, status_code=422)


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchProjectListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_project_create(team_id: str, payload: ResearchProjectCreatePayload) -> dict:
    try:
        return create_research_project(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("research_project.create", team_id, exc, status_code=404)
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error("research_project.create", team_id, exc, status_code=422)


@router.patch(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}",
    response_model=ResearchProjectListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_project_update(
    team_id: str,
    project_id: str,
    payload: ResearchProjectUpdatePayload,
) -> dict:
    try:
        return update_research_project(team_id, project_id, payload.model_dump(exclude_unset=True))
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project.update",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except ResearchProjectNameLockedError as exc:
        _raise_team_workflow_route_error(
            "research_project.update",
            team_id,
            exc,
            status_code=409,
            fields={
                "projectId": project_id,
                "code": ResearchProjectNameLockedError.code,
            },
            detail={
                "code": ResearchProjectNameLockedError.code,
                "message": str(exc),
            },
        )
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error(
            "research_project.update",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/activate",
    response_model=ResearchProjectListResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_project_activate(team_id: str, project_id: str) -> dict:
    try:
        return activate_research_project(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project.activate",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error(
            "research_project.activate",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/progress",
    response_model=ResearchProjectProgressResponse,
)
def team_workflow_research_project_progress(team_id: str, project_id: str) -> dict:
    try:
        return get_research_project_progress(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project.progress",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except (ResearchProjectError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_project.progress",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/source-collection/reset",
    response_model=ResearchProjectSourceCollectionResetResponse,
)
def team_workflow_research_project_source_collection_reset(team_id: str, project_id: str) -> dict:
    try:
        return reset_research_project_source_collection(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project.source_collection_reset",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except (ResearchProjectError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_project.source_collection_reset",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/progress/reset",
    response_model=ResearchProjectSourceCollectionResetResponse,
)
def team_workflow_research_project_progress_reset(team_id: str, project_id: str) -> dict:
    """Explicit project cascade: sources + experiment/iteration owned by this project."""

    try:
        return reset_research_project_progress(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project.progress_reset",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except (ResearchProjectError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_project.progress_reset",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/agent-tasks/status",
    response_model=ResearchProjectAgentTaskStatusResponse,
)
def team_workflow_research_project_agent_task_status(
    team_id: str,
    project_id: str,
) -> dict:
    try:
        return get_research_project_agent_task_status(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.status",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except (ResearchProjectError, ResearchProjectAgentTaskError) as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.status",
            team_id,
            exc,
            status_code=422,
            fields={
                "projectId": project_id,
                "code": getattr(exc, "code", ""),
            },
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/agent-tasks/start",
    status_code=status.HTTP_201_CREATED,
    response_model=ResearchProjectAgentTaskStartResponse,
)
def team_workflow_research_project_agent_task_start(
    team_id: str,
    project_id: str,
    payload: ResearchProjectAgentTaskStartPayload,
) -> dict:
    try:
        return start_research_project_agent_task(
            team_id,
            project_id,
            payload.model_dump(),
        )
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.start",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id, "taskKind": payload.taskKind},
        )
    except ResearchProjectAgentTaskError as exc:
        conflict_codes = {
            "agent_role_unbound",
            "agent_role_mismatch",
            "agent_task_active",
            "invalid_retry_source",
            "retry_task_not_terminal",
            "retry_task_required",
            "session_resolution_failed",
            "task_store_inconsistent",
        }
        response_status = 409 if exc.code in conflict_codes else 422
        _raise_team_workflow_route_error(
            "research_project_agent_task.start",
            team_id,
            exc,
            status_code=response_status,
            fields={
                "projectId": project_id,
                "taskKind": payload.taskKind,
                "code": exc.code,
            },
            detail={"code": exc.code, "message": str(exc)},
        )
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.start",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id, "taskKind": payload.taskKind},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/research-projects/{project_id}/agent-tasks/reconcile",
    response_model=ResearchProjectAgentTaskReconcileResponse,
    response_model_exclude_unset=True,
)
def team_workflow_research_project_agent_task_reconcile(
    team_id: str,
    project_id: str,
) -> dict:
    """Operator maintenance: align active Agent tasks with session truth.

    Explicit write path for operators after backend restarts or crashes leave
    a task stuck in ``running`` while its session already reached a terminal
    state; read surfaces never reconcile. Idempotent: repeated calls only
    re-derive the same verdict and never create tasks or sessions.
    """
    try:
        result = reconcile_research_project_agent_task_statuses(team_id, project_id)
    except (TeamNotFoundError, ResearchProjectNotFoundError) as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.reconcile",
            team_id,
            exc,
            status_code=404,
            fields={"projectId": project_id},
        )
    except ResearchProjectAgentTaskError as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.reconcile",
            team_id,
            exc,
            status_code=422,
            fields={
                "projectId": project_id,
                "code": getattr(exc, "code", ""),
            },
            detail={"code": exc.code, "message": str(exc)},
        )
    except ResearchProjectError as exc:
        _raise_team_workflow_route_error(
            "research_project_agent_task.reconcile",
            team_id,
            exc,
            status_code=422,
            fields={"projectId": project_id},
        )
    return {"teamId": team_id, "researchProjectId": project_id, **result}
