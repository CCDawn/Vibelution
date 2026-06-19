"""Team workflow orchestration API routes."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from core.web.services.team_service import TeamNotFoundError, TeamServiceError
from core.web.services.team_workflow_orchestration_service import (
    DEFAULT_OWNER_AGENT_ID,
    WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH,
    TeamWorkflowOrchestrationError,
    assess_source_candidate_quality,
    assess_source_quality_batch,
    build_candidate_graph,
    create_experiment_plan,
    decide_transfer_request,
    ensure_team_workflow_orchestration,
    execute_source_collection_search,
    extract_source_collection_candidates,
    get_experiment_planning_status,
    get_knowledge_ingestion_status,
    get_official_model_evidence_status,
    get_paper_note_chunk_status,
    get_research_stage_round_status,
    get_source_quality_status,
    get_team_workflow_coordination_status,
    get_team_workflow_orchestration,
    build_local_research_model_task,
    draft_paper_note_from_source_candidate,
    extract_candidate_source_pages,
    import_data_record_as_source_candidate,
    invoke_local_research_model,
    list_candidate_store,
    open_source_collection_storage_target,
    plan_paper_note_chunks_from_source_candidate,
    record_local_research_model_output,
    register_experiment_baseline_artifact,
    register_experiment_full_run_result,
    register_experiment_smoke_result,
    register_official_model_evidence,
    register_candidate_source,
    request_experiment_result_knowledge_ingestion,
    review_steward_pack_knowledge_ingestion,
    retry_research_stage_round_coordination,
    retry_research_stage_round_memory_record,
    run_knowledge_collection_ingestion,
    run_knowledge_ingestion_precheck,
    start_research_stage_round,
    start_source_collection_search_background,
    start_source_collection_run,
    submit_transfer_request,
    submit_steward_pack_to_knowledge_ingestion,
    validate_candidate_store,
)
from core.web.services.runtime_scene_service import record_runtime_scene_event


router = APIRouter(tags=["team-workflows"])


def _truncate_route_field(value: Any, *, limit: int = 240) -> str:
    return str(value or "").strip()[:limit]


def _raise_team_workflow_route_error(
    action: str,
    team_id: str,
    exc: Exception,
    *,
    status_code: int,
    fields: dict[str, Any] | None = None,
) -> NoReturn:
    event_fields = {
        "action": _truncate_route_field(action, limit=120),
        "teamId": _truncate_route_field(team_id, limit=160),
        "statusCode": status_code,
        "errorType": type(exc).__name__,
        "errorDetail": _truncate_route_field(exc, limit=320),
    }
    if fields:
        event_fields.update({key: _truncate_route_field(value) for key, value in fields.items()})
    try:
        record_runtime_scene_event(
            "team_workflow_orchestration",
            "route_error",
            "team_workflow.route_error",
            message=f"{action} blocked at the Team Workflow API route.",
            level="warning" if status_code < 500 else "error",
            outcome="blocked" if status_code in {400, 403, 404, 409, 422} else "failed",
            fields=event_fields,
            lifecycle=True,
        )
    except Exception:
        pass
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


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


class DataRecordSourceImportPayload(BaseModel):
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


class SourceCollectionRunStartPayload(BaseModel):
    title: str = Field("", max_length=180)
    goal: str = Field("", max_length=1000)
    topic: str = Field("", max_length=500)
    ownerAgentId: str = Field("", max_length=160)
    requestedByAgent: str = Field("", max_length=160)
    agentRoles: list[str] = Field(default_factory=list, max_length=8)
    agentIds: dict[str, str] = Field(default_factory=dict)
    inputRefs: list[str] = Field(default_factory=list, max_length=120)
    querySeeds: list[str] = Field(default_factory=list, max_length=40)
    searchLanguages: list[str] = Field(default_factory=list, max_length=8)
    sourceTypes: list[str] = Field(default_factory=list, max_length=16)
    maxResultsPerQuery: int = Field(10, ge=1, le=100)
    promptCachePolicy: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)


class SourceCollectionSearchExecutePayload(BaseModel):
    assignmentIds: list[str] = Field(default_factory=list, max_length=16)
    agentRole: str = Field("", max_length=80)
    maxQueries: int = Field(4, ge=1, le=12)
    maxResultsPerQuery: int = Field(2, ge=1, le=5)
    provider: str = Field("crossref_rest_api", max_length=80)
    force: bool = False
    backgroundExecution: bool = False


class SourceCollectionStorageOpenPayload(BaseModel):
    target: str = Field("run_directory", max_length=80)


class ResearchStageRoundStartPayload(BaseModel):
    stageType: str = Field("knowledge_collection", max_length=80)
    mode: str = Field("continue_or_start", max_length=80)
    title: str = Field("", max_length=180)
    topic: str = Field("", max_length=500)
    goal: str = Field("", max_length=1000)
    ownerAgentId: str = Field("", max_length=160)
    requestedByAgent: str = Field("", max_length=160)
    upstreamRoundIds: list[str] = Field(default_factory=list, max_length=24)
    agentRoles: list[str] = Field(default_factory=list, max_length=8)
    agentIds: dict[str, str] = Field(default_factory=dict)
    inputRefs: list[str] = Field(default_factory=list, max_length=120)
    querySeeds: list[str] = Field(default_factory=list, max_length=40)
    searchLanguages: list[str] = Field(default_factory=list, max_length=8)
    sourceTypes: list[str] = Field(default_factory=list, max_length=16)
    maxResultsPerQuery: int = Field(10, ge=1, le=100)
    promptCachePolicy: dict[str, Any] = Field(default_factory=dict)
    scope: dict[str, Any] = Field(default_factory=dict)


class ExperimentPlanCreatePayload(BaseModel):
    stageRoundId: str = Field("", max_length=128)
    title: str = Field("", max_length=240)
    createdByAgent: str = Field("", max_length=160)
    hypothesisCandidateIds: list[str] = Field(default_factory=list, max_length=16)
    dataset: str = Field("", max_length=500)
    metric: str = Field("", max_length=500)
    baseline: str = Field("", max_length=500)
    smokePlan: str = Field("", max_length=1200)
    experimentPlan: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field("", max_length=4000)


class ExperimentBaselineArtifactPayload(BaseModel):
    registeredByAgent: str = Field("", max_length=160)
    baselineName: str = Field("", max_length=500)
    datasetRef: str = Field("", max_length=500)
    metricName: str = Field("", max_length=500)
    metricValue: str = Field("", max_length=240)
    artifactPath: str = Field("", max_length=500)
    evidenceRef: str = Field("", max_length=500)
    reproductionCommand: str = Field("", max_length=1200)
    evaluationCommand: str = Field("", max_length=1200)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    notes: str = Field("", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentSmokeResultPayload(BaseModel):
    recordedByAgent: str = Field("", max_length=160)
    status: str = Field("needs_review", max_length=80)
    metricName: str = Field("", max_length=500)
    metricValue: str = Field("", max_length=240)
    baselineMetricValue: str = Field("", max_length=240)
    delta: str = Field("", max_length=240)
    resultPath: str = Field("", max_length=500)
    logRef: str = Field("", max_length=500)
    evaluationCommand: str = Field("", max_length=1200)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    notes: str = Field("", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentFullRunResultPayload(BaseModel):
    recordedByAgent: str = Field("", max_length=160)
    status: str = Field("needs_review", max_length=80)
    metricName: str = Field("", max_length=500)
    metricValue: str = Field("", max_length=240)
    baselineMetricValue: str = Field("", max_length=240)
    smokeMetricValue: str = Field("", max_length=240)
    delta: str = Field("", max_length=240)
    resultPath: str = Field("", max_length=500)
    logRef: str = Field("", max_length=500)
    configPath: str = Field("", max_length=500)
    reproductionCommand: str = Field("", max_length=1200)
    evaluationCommand: str = Field("", max_length=1200)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    notes: str = Field("", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExperimentResultKnowledgeIngestionPayload(BaseModel):
    requestedByAgent: str = Field("", max_length=160)
    stewardAgentId: str = Field("", max_length=160)
    knowledgeBaseId: str = Field("", max_length=160)
    targetDomain: str = Field("", max_length=240)
    wakeStewardAgent: bool = True
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=12)
    notes: str = Field("", max_length=4000)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class OfficialModelEvidencePayload(BaseModel):
    taskType: str = Field("", max_length=80)
    workflowNode: str = Field("", max_length=120)
    candidateId: str = Field("", max_length=128)
    stageRoundId: str = Field("", max_length=128)
    sourceRunId: str = Field("", max_length=128)
    taskId: str = Field("", max_length=128)
    modelProvider: str = Field("", max_length=120)
    modelId: str = Field("", max_length=160)
    modelName: str = Field("", max_length=240)
    modelProfileId: str = Field("", max_length=160)
    evidenceKind: str = Field("", max_length=80)
    artifactPath: str = Field("", max_length=500)
    screenshotPath: str = Field("", max_length=500)
    logRef: str = Field("", max_length=500)
    promptSummary: str = Field("", max_length=1200)
    outputSummary: str = Field("", max_length=1200)
    sourceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    status: str = Field("", max_length=80)
    recordedByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CandidateGraphBuildPayload(BaseModel):
    title: str = Field("", max_length=240)
    createdByAgent: str = Field("", max_length=160)
    curationMode: str = Field("", max_length=80)


class KnowledgeIngestionPrecheckPayload(BaseModel):
    stewardAgentId: str = Field("", max_length=160)
    maxCandidates: int = Field(32, ge=1, le=200)
    targetDomain: str = Field("", max_length=240)
    notes: str = Field("", max_length=4000)


class KnowledgeCollectionIngestionPayload(BaseModel):
    sourceQualityAgentId: str = Field("", max_length=160)
    candidateGraphAgentId: str = Field("", max_length=160)
    stewardAgentId: str = Field("", max_length=160)
    knowledgeBaseId: str = Field("", max_length=128)
    targetDomain: str = Field("", max_length=240)
    maxCandidates: int = Field(80, ge=1, le=200)
    forceReview: bool = False
    autoCreateKnowledgeBase: bool = True
    autoSubmit: bool = False
    autoReviewSource: bool = False
    autoApprove: bool = False
    notifyStewardAgent: bool = True
    wakeStewardAgent: bool = True
    requesterAgentId: str = Field("", max_length=160)


class KnowledgeCollectionExtractionPayload(BaseModel):
    runId: str = Field("", max_length=128)
    extractionAgentId: str = Field("", max_length=160)
    maxRecords: int = Field(100, ge=1, le=500)
    force: bool = False
    notes: str = Field("", max_length=4000)


class SourceExtractionPayload(BaseModel):
    createdByAgent: str = Field("", max_length=160)
    pageScope: str = Field("", max_length=160)
    allowedForAnalysis: bool | None = None
    maxPages: int = Field(24, ge=1, le=64)
    maxCharsPerPage: int = Field(1800, ge=200, le=6000)


class PaperNoteAutodraftPayload(BaseModel):
    createdByAgent: str = Field("", max_length=160)
    modelId: str = Field("", max_length=160)
    title: str = Field("", max_length=240)
    summary: str = Field("", max_length=4000)
    excerpt: str = Field("", max_length=24000)
    chunkId: str = Field("", max_length=128)


class PaperNoteChunkPlanPayload(BaseModel):
    createdByAgent: str = Field("", max_length=160)
    maxPagesPerChunk: int = Field(4, ge=1, le=12)
    maxCharsPerChunk: int = Field(12000, ge=2000, le=24000)


class SourceQualityAssessmentPayload(BaseModel):
    assessedByAgent: str = Field("", max_length=160)
    decision: str = Field("", max_length=80)
    relevanceScore: int | None = Field(None, ge=0, le=100)
    reliabilityScore: int | None = Field(None, ge=0, le=100)
    accessibilityScore: int | None = Field(None, ge=0, le=100)
    extractionReadinessScore: int | None = Field(None, ge=0, le=100)
    notes: str = Field("", max_length=4000)
    requiredFixes: list[str] = Field(default_factory=list, max_length=12)
    riskFlags: list[str] = Field(default_factory=list, max_length=12)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)


class SourceQualityBatchAssessmentPayload(BaseModel):
    assessedByAgent: str = Field("", max_length=160)
    candidateIds: list[str] = Field(default_factory=list, max_length=200)
    maxCandidates: int = Field(100, ge=1, le=200)
    force: bool = False
    notes: str = Field("", max_length=4000)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)


class StewardPackKnowledgeIngestionPayload(BaseModel):
    knowledgeBaseId: str = Field("", max_length=128)
    proposedByAgentId: str = Field("", max_length=160)
    centralSourceId: str = Field("", max_length=160)


class StewardPackKnowledgeIngestionReviewPayload(BaseModel):
    knowledgeBaseId: str = Field("", max_length=128)
    reviewedByAgentId: str = Field("", max_length=160)
    decision: str = Field("", max_length=32)
    resolutionNote: str = Field("", max_length=2000)


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


@router.post("/teams/{team_id}/workflow-orchestration/source-collection-runs", status_code=status.HTTP_201_CREATED)
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


@router.get("/teams/{team_id}/workflow-orchestration/experiments/status")
def team_workflow_experiment_planning_status(team_id: str) -> dict:
    try:
        return get_experiment_planning_status(team_id)
    except TeamNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/teams/{team_id}/workflow-orchestration/experiments/plan", status_code=status.HTTP_201_CREATED)
def team_workflow_experiment_plan_create(team_id: str, payload: ExperimentPlanCreatePayload) -> dict:
    try:
        return create_experiment_plan(team_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_plan.create",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": payload.stageRoundId, "createdByAgent": payload.createdByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_plan.create",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": payload.stageRoundId, "createdByAgent": payload.createdByAgent},
        )


@router.post("/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/baseline-artifact", status_code=status.HTTP_201_CREATED)
def team_workflow_experiment_baseline_artifact_register(team_id: str, plan_id: str, payload: ExperimentBaselineArtifactPayload) -> dict:
    try:
        return register_experiment_baseline_artifact(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_baseline_artifact.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "registeredByAgent": payload.registeredByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_baseline_artifact.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "registeredByAgent": payload.registeredByAgent, "artifactPath": payload.artifactPath},
        )


@router.post("/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/smoke-result", status_code=status.HTTP_201_CREATED)
def team_workflow_experiment_smoke_result_register(team_id: str, plan_id: str, payload: ExperimentSmokeResultPayload) -> dict:
    try:
        return register_experiment_smoke_result(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_result.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_smoke_result.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent, "status": payload.status},
        )


@router.post("/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/full-run-result", status_code=status.HTTP_201_CREATED)
def team_workflow_experiment_full_run_result_register(team_id: str, plan_id: str, payload: ExperimentFullRunResultPayload) -> dict:
    try:
        return register_experiment_full_run_result(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run_result.register",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_full_run_result.register",
            team_id,
            exc,
            status_code=422,
            fields={"planId": plan_id, "recordedByAgent": payload.recordedByAgent, "status": payload.status},
        )


@router.post("/teams/{team_id}/workflow-orchestration/experiments/plans/{plan_id}/knowledge-ingestion-request", status_code=status.HTTP_201_CREATED)
def team_workflow_experiment_result_knowledge_ingestion_request(team_id: str, plan_id: str, payload: ExperimentResultKnowledgeIngestionPayload) -> dict:
    try:
        return request_experiment_result_knowledge_ingestion(team_id, plan_id, payload.model_dump())
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "experiment_result_knowledge_ingestion.request",
            team_id,
            exc,
            status_code=404,
            fields={"planId": plan_id, "requestedByAgent": payload.requestedByAgent},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "experiment_result_knowledge_ingestion.request",
            team_id,
            exc,
            status_code=422,
            fields={
                "planId": plan_id,
                "requestedByAgent": payload.requestedByAgent,
                "stewardAgentId": payload.stewardAgentId,
                "knowledgeBaseId": payload.knowledgeBaseId,
            },
        )


@router.post("/teams/{team_id}/workflow-orchestration/stage-rounds/{stage_round_id}/coordination/retry")
def team_workflow_research_stage_round_coordination_retry(team_id: str, stage_round_id: str) -> dict:
    try:
        return retry_research_stage_round_coordination(team_id, stage_round_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.coordination_retry",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": stage_round_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.coordination_retry",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": stage_round_id},
        )


@router.post("/teams/{team_id}/workflow-orchestration/stage-rounds/{stage_round_id}/memory-record/retry")
def team_workflow_research_stage_round_memory_retry(team_id: str, stage_round_id: str) -> dict:
    try:
        return retry_research_stage_round_memory_record(team_id, stage_round_id)
    except TeamNotFoundError as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.memory_retry",
            team_id,
            exc,
            status_code=404,
            fields={"stageRoundId": stage_round_id},
        )
    except (TeamServiceError, TeamWorkflowOrchestrationError) as exc:
        _raise_team_workflow_route_error(
            "research_stage_round.memory_retry",
            team_id,
            exc,
            status_code=422,
            fields={"stageRoundId": stage_round_id},
        )


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
        return run_knowledge_collection_ingestion(team_id, payload.model_dump())
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
