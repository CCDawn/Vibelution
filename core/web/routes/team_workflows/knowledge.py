"""Team workflow routes: knowledge."""
from __future__ import annotations
from fastapi import Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router

@router.get("/teams/{team_id}/workflow-orchestration/knowledge-ingestion/status")
def team_workflow_knowledge_ingestion_status(team_id: str) -> dict:
    try:
        return get_knowledge_ingestion_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-ingestion/precheck", status_code=status.HTTP_201_CREATED)
def team_workflow_knowledge_ingestion_precheck(team_id: str, payload: KnowledgeIngestionPrecheckPayload) -> dict:
    try:
        return run_knowledge_ingestion_precheck(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("knowledge_ingestion.precheck", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_ingestion.precheck",
            team_id,
            exc,
            status_code=422,
            fields={"stewardAgentId": payload.stewardAgentId},
        )


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-collection/extract", status_code=status.HTTP_201_CREATED)
def team_workflow_knowledge_collection_extract(team_id: str, payload: KnowledgeCollectionExtractionPayload) -> dict:
    try:
        return extract_source_collection_candidates(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("knowledge_collection.extract", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_collection.extract",
            team_id,
            exc,
            status_code=422,
            fields={
                "runId": payload.runId,
                "extractionAgentId": payload.extractionAgentId,
                "force": payload.force,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-collection/ingest", status_code=status.HTTP_201_CREATED)
def team_workflow_knowledge_collection_ingest(team_id: str, payload: KnowledgeCollectionIngestionPayload) -> dict:
    try:
        payload_dict = payload.model_dump()
        if payload.backgroundExecution:
            return start_knowledge_collection_ingestion_background(team_id, payload_dict)
        return run_knowledge_collection_ingestion(team_id, payload_dict)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("knowledge_collection.ingest", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_collection.ingest",
            team_id,
            exc,
            status_code=422,
            fields={
                "stewardAgentId": payload.stewardAgentId,
                "knowledgeBaseId": payload.knowledgeBaseId,
                "autoApprove": payload.autoApprove,
                "notifyStewardAgent": payload.notifyStewardAgent,
                "wakeStewardAgent": payload.wakeStewardAgent,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-collection/complete", status_code=status.HTTP_201_CREATED)
def team_workflow_knowledge_collection_complete(team_id: str, payload: KnowledgeCollectionIngestionPayload) -> dict:
    try:
        payload_dict = payload.model_dump()
        payload_dict.update(
            {
                "backgroundExecution": True,
                "autoCreateKnowledgeBase": True,
                "autoSubmit": True,
                "autoReviewSource": True,
                "autoApprove": True,
                "notifyStewardAgent": False,
                "wakeStewardAgent": False,
            }
        )
        return start_knowledge_collection_completion_background(team_id, payload_dict)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("knowledge_collection.complete", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_collection.complete",
            team_id,
            exc,
            status_code=422,
            fields={
                "stewardAgentId": payload.stewardAgentId,
                "knowledgeBaseId": payload.knowledgeBaseId,
                "autoApprove": True,
            },
        )


@router.get("/teams/{team_id}/workflow-orchestration/coordination/status")
def team_workflow_coordination_status(team_id: str) -> dict:
    try:
        return get_team_workflow_coordination_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/candidate-graph", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_graph_build(team_id: str, payload: CandidateGraphBuildPayload) -> dict:
    try:
        return build_candidate_graph(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("candidate_graph.build", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate_graph.build",
            team_id,
            exc,
            status_code=422,
            fields={"createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/source-extraction")
def team_workflow_candidate_source_extract(team_id: str, candidate_id: str, payload: SourceExtractionPayload) -> dict:
    try:
        return extract_candidate_source_pages(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "candidate_source.extract",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate_source.extract",
            team_id,
            exc,
            status_code=422,
            fields={"candidateId": candidate_id, "createdByAgent": payload.createdByAgent, "pageScope": payload.pageScope},
        )


@router.post("/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-draft", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_paper_note_autodraft(team_id: str, candidate_id: str, payload: PaperNoteAutodraftPayload) -> dict:
    try:
        return draft_paper_note_from_source_candidate(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "candidate.paper_note_draft",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate.paper_note_draft",
            team_id,
            exc,
            status_code=422,
            fields={"candidateId": candidate_id, "createdByAgent": payload.createdByAgent, "modelId": payload.modelId},
        )
