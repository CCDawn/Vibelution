"""Team workflow routes: research_ops."""
from __future__ import annotations
from fastapi import Query, status
from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import *
from ._errors import _raise_team_workflow_route_error
from ._models import *
from ._router import router

@router.post("/teams/{team_id}/workflow-orchestration/research/mechanisms/extract", status_code=status.HTTP_201_CREATED)
def team_workflow_research_mechanisms_extract(team_id: str, payload: NeuroMechanismExtractPayload) -> dict:
    try:
        return extract_neuro_mechanism_from_paper_note(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research.mechanisms_extract",
            team_id,
            exc,
            status_code=404,
            fields={"paperNoteId": payload.paperNoteId},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research.mechanisms_extract",
            team_id,
            exc,
            status_code=422,
            fields={"paperNoteId": payload.paperNoteId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/research/mechanisms/map", status_code=status.HTTP_201_CREATED)
def team_workflow_research_mechanisms_map(team_id: str, payload: MechanismMappingPayload) -> dict:
    try:
        return map_mechanism_to_abstraction(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research.mechanisms_map", team_id, exc, status_code=404, fields={"mechanismId": payload.mechanismId}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research.mechanisms_map",
            team_id,
            exc,
            status_code=422,
            fields={"mechanismId": payload.mechanismId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/research/hypotheses/generate", status_code=status.HTTP_201_CREATED)
def team_workflow_research_hypotheses_generate(team_id: str, payload: AlgorithmHypothesisPayload) -> dict:
    try:
        return generate_algorithm_hypothesis_from_mechanism_mapping(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research.hypotheses_generate", team_id, exc, status_code=404, fields={"mappingId": payload.mappingId}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research.hypotheses_generate",
            team_id,
            exc,
            status_code=422,
            fields={"mappingId": payload.mappingId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/research/review/decide", status_code=status.HTTP_201_CREATED)
def team_workflow_research_review_decide(team_id: str, payload: ResearchReviewDecidePayload) -> dict:
    try:
        return decide_research_review(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research.review_decide", team_id, exc, status_code=404, fields={"decision": payload.decision}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research.review_decide",
            team_id,
            exc,
            status_code=422,
            fields={"decision": payload.decision, "reviewedByAgent": payload.reviewedByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/iterations/propose", status_code=status.HTTP_201_CREATED)
def team_workflow_iterations_propose(team_id: str, payload: IterationProposePayload) -> dict:
    try:
        return propose_iteration(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "iterations.propose", team_id, exc, status_code=404, fields={"parentCandidateId": payload.parentCandidateId}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "iterations.propose",
            team_id,
            exc,
            status_code=422,
            fields={"parentCandidateId": payload.parentCandidateId, "action": payload.action},
        )


@router.post("/teams/{team_id}/workflow-orchestration/deliverables/export", status_code=status.HTTP_201_CREATED)
def team_workflow_deliverables_export(team_id: str, payload: DeliverableExportPayload) -> dict:
    try:
        return export_deliverables(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "deliverables.export", team_id, exc, status_code=404, fields={"requestedByAgent": payload.requestedByAgent}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "deliverables.export",
            team_id,
            exc,
            status_code=422,
            fields={"requestedByAgent": payload.requestedByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/prd/validate", status_code=status.HTTP_201_CREATED)
def team_workflow_prd_validate(team_id: str, payload: PrdValidatePayload) -> dict:
    try:
        registered_paths = [str(getattr(route, "path", "")) for route in router.routes]
        return validate_prd(team_id, payload.model_dump(), registered_paths=registered_paths)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "prd.validate", team_id, exc, status_code=404, fields={"requestedByAgent": payload.requestedByAgent}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "prd.validate",
            team_id,
            exc,
            status_code=422,
            fields={"requestedByAgent": payload.requestedByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-graph/sync", status_code=status.HTTP_201_CREATED)
def team_workflow_knowledge_graph_sync(team_id: str, payload: KnowledgeGraphSyncPayload) -> dict:
    try:
        return sync_official_research_graph(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "knowledge_graph.sync", team_id, exc, status_code=404, fields={"syncedByAgent": payload.syncedByAgent}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_graph.sync",
            team_id,
            exc,
            status_code=422,
            fields={"syncedByAgent": payload.syncedByAgent, "force": payload.force},
        )


@router.post("/teams/{team_id}/workflow-orchestration/knowledge-graph/{sync_id}/rollback")
def team_workflow_knowledge_graph_rollback(team_id: str, sync_id: str, payload: KnowledgeGraphRollbackPayload) -> dict:
    try:
        return rollback_official_research_graph(team_id, sync_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "knowledge_graph.rollback", team_id, exc, status_code=404, fields={"syncId": sync_id}
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "knowledge_graph.rollback",
            team_id,
            exc,
            status_code=422,
            fields={"syncId": sync_id, "rolledBackByAgent": payload.rolledBackByAgent},
        )


@router.get("/teams/{team_id}/workflow-orchestration/paper-note-chunks/status")
def team_workflow_paper_note_chunk_status(team_id: str) -> dict:
    try:
        return get_paper_note_chunk_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/teams/{team_id}/workflow-orchestration/source-quality/status")
def team_workflow_source_quality_status(team_id: str) -> dict:
    try:
        return get_source_quality_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/source-quality/assess-batch", status_code=status.HTTP_201_CREATED)
def team_workflow_source_quality_assess_batch(team_id: str, payload: SourceQualityBatchAssessmentPayload) -> dict:
    try:
        return assess_source_quality_batch(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "source_quality.assess_batch",
            team_id,
            exc,
            status_code=404,
            fields={"assessedByAgent": payload.assessedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "source_quality.assess_batch",
            team_id,
            exc,
            status_code=422,
            fields={"assessedByAgent": payload.assessedByAgent, "maxCandidates": payload.maxCandidates},
        )


@router.post("/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/source-quality/assess", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_source_quality_assess(team_id: str, candidate_id: str, payload: SourceQualityAssessmentPayload) -> dict:
    try:
        return assess_source_candidate_quality(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "candidate.source_quality_assess",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate.source_quality_assess",
            team_id,
            exc,
            status_code=422,
            fields={"candidateId": candidate_id, "assessedByAgent": payload.assessedByAgent, "decision": payload.decision},
        )


@router.post("/teams/{team_id}/workflow-orchestration/candidates/{candidate_id}/paper-note-chunks/plan", status_code=status.HTTP_201_CREATED)
def team_workflow_candidate_paper_note_chunks_plan(team_id: str, candidate_id: str, payload: PaperNoteChunkPlanPayload) -> dict:
    try:
        return plan_paper_note_chunks_from_source_candidate(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "candidate.paper_note_chunks_plan",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "candidate.paper_note_chunks_plan",
            team_id,
            exc,
            status_code=422,
            fields={"candidateId": candidate_id, "createdByAgent": payload.createdByAgent},
        )


@router.post(
    "/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion",
    status_code=status.HTTP_201_CREATED,
)
def team_workflow_steward_pack_knowledge_ingestion_submit(
    team_id: str,
    candidate_id: str,
    payload: StewardPackKnowledgeIngestionPayload,
) -> dict:
    try:
        return submit_steward_pack_to_knowledge_ingestion(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "steward_pack.knowledge_ingestion_submit",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "steward_pack.knowledge_ingestion_submit",
            team_id,
            exc,
            status_code=422,
            fields={
                "candidateId": candidate_id,
                "knowledgeBaseId": payload.knowledgeBaseId,
                "proposedByAgentId": payload.proposedByAgentId,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/steward-packs/{candidate_id}/knowledge-ingestion/review")
def team_workflow_steward_pack_knowledge_ingestion_review(
    team_id: str,
    candidate_id: str,
    payload: StewardPackKnowledgeIngestionReviewPayload,
) -> dict:
    try:
        return review_steward_pack_knowledge_ingestion(team_id, candidate_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "steward_pack.knowledge_ingestion_review",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": candidate_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "steward_pack.knowledge_ingestion_review",
            team_id,
            exc,
            status_code=422,
            fields={
                "candidateId": candidate_id,
                "knowledgeBaseId": payload.knowledgeBaseId,
                "reviewedByAgentId": payload.reviewedByAgentId,
                "decision": payload.decision,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/transfers", status_code=status.HTTP_201_CREATED)
def team_workflow_transfer_create(team_id: str, payload: TransferRequestPayload) -> dict:
    try:
        return submit_transfer_request(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "transfer.create",
            team_id,
            exc,
            status_code=404,
            fields={"candidateId": payload.candidateId},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "transfer.create",
            team_id,
            exc,
            status_code=422,
            fields={
                "candidateId": payload.candidateId,
                "fromNode": payload.fromNode,
                "toNode": payload.toNode,
                "requestedByAgent": payload.requestedByAgent,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/transfers/{transfer_id}/decide")
def team_workflow_transfer_decide(team_id: str, transfer_id: str, payload: TransferDecisionPayload) -> dict:
    try:
        return decide_transfer_request(team_id, transfer_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "transfer.decide",
            team_id,
            exc,
            status_code=404,
            fields={"transferId": transfer_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "transfer.decide",
            team_id,
            exc,
            status_code=422,
            fields={"transferId": transfer_id, "decision": payload.decision, "decidedByAgent": payload.decidedByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/tasks", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_task_create(team_id: str, payload: LocalResearchModelTaskPayload) -> dict:
    try:
        return build_local_research_model_task(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("local_research_model.task_create", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "local_research_model.task_create",
            team_id,
            exc,
            status_code=422,
            fields={"taskType": payload.taskType, "modelId": payload.modelId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/outputs", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_output_create(team_id: str, payload: LocalResearchModelOutputPayload) -> dict:
    try:
        return record_local_research_model_output(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("local_research_model.output_create", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "local_research_model.output_create",
            team_id,
            exc,
            status_code=422,
            fields={"taskType": payload.taskType, "modelId": payload.modelId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/local-research-model/invoke", status_code=status.HTTP_201_CREATED)
def team_workflow_local_research_model_invoke(team_id: str, payload: LocalResearchModelInvokePayload) -> dict:
    try:
        return invoke_local_research_model(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("local_research_model.invoke", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "local_research_model.invoke",
            team_id,
            exc,
            status_code=422,
            fields={"taskType": payload.taskType, "modelId": payload.modelId, "createdByAgent": payload.createdByAgent},
        )


@router.get("/teams/{team_id}/workflow-orchestration/official-model-evidence/status")
def team_workflow_official_model_evidence_status(team_id: str) -> dict:
    try:
        return get_official_model_evidence_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/official-model-evidence", status_code=status.HTTP_201_CREATED)
def team_workflow_official_model_evidence_register(team_id: str, payload: OfficialModelEvidencePayload) -> dict:
    try:
        return register_official_model_evidence(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error("official_model_evidence.register", team_id, exc, status_code=404)
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "official_model_evidence.register",
            team_id,
            exc,
            status_code=422,
            fields={
                "taskType": payload.taskType,
                "workflowNode": payload.workflowNode,
                "candidateId": payload.candidateId,
                "modelId": payload.modelId,
                "evidenceKind": payload.evidenceKind,
            },
        )
