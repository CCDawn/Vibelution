"""Team workflow routes: source_collection."""
from __future__ import annotations
from fastapi import Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router
from .source_collection_catalog_models import SourceCollectionSummaryResponse
from .source_collection_write_models import (
    SourceCollectionAgentSessionContextResponse,
    SourceCollectionRunStartResponse,
    SourceCollectionStageSessionTaskResponse,
)

@router.post("/teams/{team_id}/workflow-orchestration/candidates/source", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_source_create(team_id: str, payload: CandidateSourcePayload) -> dict:
    try:
        return register_candidate_source(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("candidate_source.create", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate_source.create",
            team_id,
            exc,
            status_code=422,
            fields={"candidateType": payload.candidateType, "sourceKind": payload.sourceKind, "createdByAgent": payload.createdByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/data-processing/runs/{run_id}/records/{record_id}/source-candidate",
    status_code=status.HTTP_201_CREATED,
)
def team_workflow_import_data_record_source_candidate(team_id: str, run_id: str, record_id: str, payload: DataRecordSourceImportPayload) -> dict:
    try:
        return import_data_record_as_source_candidate(team_id, run_id, record_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "data_record_source_candidate.import",
            team_id,
            exc,
            status_code=404,
            fields={"runId": run_id, "recordId": record_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "data_record_source_candidate.import",
            team_id,
            exc,
            status_code=422,
            fields={"runId": run_id, "recordId": record_id, "sourceKind": payload.sourceKind, "createdByAgent": payload.createdByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/source-collection-runs",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceCollectionRunStartResponse,
    response_model_exclude_unset=True,
)
def team_workflow_source_collection_run_start(team_id: str, payload: SourceCollectionRunStartPayload) -> dict:
    try:
        return start_source_collection_run(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("source_collection_run.start", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_run.start",
            team_id,
            exc,
            status_code=422,
            fields={"ownerAgentId": payload.ownerAgentId, "requestedByAgent": payload.requestedByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/source-collection-runs/{run_id}/search/execute", status_code=status.HTTP_201_CREATED)
def team_workflow_source_collection_search_execute(team_id: str, run_id: str, payload: SourceCollectionSearchExecutePayload) -> dict:
    try:
        payload_dict = payload.model_dump()
        if payload.backgroundExecution:
            return start_source_collection_search_background(team_id, run_id, payload_dict)
        return execute_source_collection_search(team_id, run_id, payload_dict)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection_search.execute",
            team_id,
            exc,
            status_code=404,
            fields={"runId": run_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_search.execute",
            team_id,
            exc,
            status_code=422,
            fields={"runId": run_id, "agentRole": payload.agentRole, "provider": payload.provider},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/source-collection-runs/{run_id}/agent-session-context",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceCollectionAgentSessionContextResponse,
    response_model_exclude_unset=True,
)
def team_workflow_source_collection_agent_session_context(team_id: str, run_id: str, payload: SourceCollectionAgentSessionContextPayload) -> dict:
    try:
        return seed_source_collection_agent_session_context(team_id, run_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection_agent_session_context.seed",
            team_id,
            exc,
            status_code=404,
            fields={"runId": run_id, "agentId": payload.agentId, "stageId": payload.stageId},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_agent_session_context.seed",
            team_id,
            exc,
            status_code=422,
            fields={"runId": run_id, "agentId": payload.agentId, "stageId": payload.stageId, "agentRole": payload.agentRole},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/source-collection-runs/{run_id}/stage-session-tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=SourceCollectionStageSessionTaskResponse,
    response_model_exclude_unset=True,
)
def team_workflow_source_collection_stage_session_task_start(team_id: str, run_id: str, payload: SourceCollectionStageSessionTaskPayload) -> dict:
    try:
        return start_source_collection_stage_session_task(team_id, run_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection_stage_session_task.start",
            team_id,
            exc,
            status_code=404,
            fields={"runId": run_id, "agentId": payload.agentId, "stageId": payload.stageId},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_stage_session_task.start",
            team_id,
            exc,
            status_code=422,
            fields={"runId": run_id, "agentId": payload.agentId, "stageId": payload.stageId, "agentRole": payload.agentRole},
        )


@router.post("/teams/{team_id}/workflow-orchestration/stage-session-tasks/{task_id}/writeback", status_code=status.HTTP_201_CREATED)
def team_workflow_source_collection_stage_session_task_writeback(team_id: str, task_id: str, payload: SourceCollectionStageSessionTaskWritebackPayload) -> dict:
    try:
        return writeback_source_collection_stage_session_task(team_id, task_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection_stage_session_task.writeback",
            team_id,
            exc,
            status_code=404,
            fields={"taskId": task_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_stage_session_task.writeback",
            team_id,
            exc,
            status_code=422,
            fields={"taskId": task_id, "status": payload.status},
        )


@router.get(
    "/teams/{team_id}/workflow-orchestration/source-collection/summary",
    response_model=SourceCollectionSummaryResponse,
    response_model_exclude_unset=True,
)
def team_workflow_source_collection_summary(team_id: str, runId: str = "") -> dict:
    try:
        return get_source_collection_summary(team_id, run_id=runId)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection.summary",
            team_id,
            exc,
            status_code=404,
            fields={"runId": runId},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection.summary",
            team_id,
            exc,
            status_code=422,
            fields={"runId": runId},
        )


@router.post("/teams/{team_id}/workflow-orchestration/source-collection-runs/{run_id}/storage/open")
def team_workflow_source_collection_storage_open(team_id: str, run_id: str, payload: SourceCollectionStorageOpenPayload) -> dict:
    try:
        return open_source_collection_storage_target(team_id, run_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_collection_storage.open",
            team_id,
            exc,
            status_code=404,
            fields={"runId": run_id, "target": payload.target},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_collection_storage.open",
            team_id,
            exc,
            status_code=422,
            fields={"runId": run_id, "target": payload.target},
        )
