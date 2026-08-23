from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from core.web.services.team_workflow_orchestration_service import DEFAULT_OWNER_AGENT_ID, WORKFLOW_KIND_CHALLENGE_CUP_RESEARCH

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
    researchProjectId: str = Field("", max_length=160)
    questionId: str = Field("", max_length=32)
    requiredModelPolicy: dict[str, Any] = Field(default_factory=dict)
    title: str = Field("", max_length=180)
    workflowPurpose: str = Field("", max_length=80)
    workflowKind: str = Field("", max_length=80)
    collectionMode: str = Field("web_search", max_length=80)
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
    localScanScope: dict[str, Any] = Field(default_factory=dict)
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


class SourceCollectionAgentSessionContextPayload(BaseModel):
    stageId: str = Field("collection", max_length=80)
    agentId: str = Field("", max_length=160)
    agentRole: str = Field("", max_length=80)


class SourceCollectionStageSessionTaskPayload(SourceCollectionAgentSessionContextPayload):
    questionId: str = Field("", max_length=32)
    requiredModelPolicy: dict[str, Any] = Field(default_factory=dict)
    requestedByAgent: str = Field("", max_length=160)
    returnTo: str = Field("", max_length=1000)
    returnLabel: str = Field("", max_length=240)
    idempotencyKey: str = Field("", max_length=240)
    formalRetry: bool = False


class SourceCollectionStageSessionTaskWritebackPayload(BaseModel):
    status: str = Field("needs_review", max_length=80)
    summary: str = Field("", max_length=4000)
    result: dict[str, Any] = Field(default_factory=dict)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)
    nextActions: list[str] = Field(default_factory=list, max_length=12)
    recordedByAgent: str = Field("", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class ResearchProjectListResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: int = 0
    teamId: str = ""
    activeProjectId: str = ""
    projects: list[dict[str, Any]] = Field(default_factory=list)
    updatedAt: str = ""
    project: dict[str, Any] = Field(default_factory=dict)


class ResearchProjectCreatePayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    topic: str = Field("", max_length=1000)
    experimentMethod: str = Field("", max_length=120)


class ResearchProjectUpdatePayload(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    topic: str | None = Field(None, max_length=1000)
    experimentMethod: str | None = Field(None, max_length=120)


class ResearchProjectSourceCollectionResetResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str
    researchProjectId: str
    experimentName: str
    includeDownstream: bool = False
    removedRunIds: list[str] = Field(default_factory=list)
    removedRunCount: int = 0
    removedSourceCandidateCount: int = 0
    removedStageRoundCount: int = 0
    removedExperimentPlanCount: int = 0
    nextAction: str = ""


class ResearchProjectProgressResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str
    researchProjectId: str
    experimentName: str = ""
    sourceRunCount: int = 0
    sourceCandidateCount: int = 0
    downstreamCandidateCount: int = 0
    stageRoundCounts: dict[str, int] = Field(default_factory=dict)
    experimentPlanCount: int = 0
    frozenExperimentPlanCount: int = 0
    currentStage: str = ""
    phases: list[dict[str, Any]] = Field(default_factory=list)
    canResetSourceOnly: bool = False
    canResetProgress: bool = False
    updatedAt: str = ""


class ResearchProjectAgentTaskStartPayload(BaseModel):
    taskKind: str = Field("", max_length=80)
    targetRef: str = Field("", max_length=200)
    idempotencyKey: str = Field("", max_length=240)
    formalRetry: bool = False
    retryTaskId: str = Field("", max_length=200)
    returnTo: str = Field("", max_length=1000)
    returnLabel: str = Field("", max_length=240)


class ResearchProjectAgentTaskTurnResponse(BaseModel):
    accepted: bool = False
    turnId: str = ""
    status: str = ""
    acceptedAt: str = ""


class ResearchProjectAgentTaskResponse(BaseModel):
    schemaVersion: int = 1
    taskId: str
    idempotencyKey: str = ""
    taskKind: str
    taskTitle: str
    teamId: str
    researchProjectId: str
    experimentName: str
    targetRef: str = ""
    agentId: str
    teamRole: str
    roleKey: str
    roleLabel: str
    sessionId: str
    sessionTitle: str
    sessionAttempt: int = 1
    sessionCreated: bool = False
    retryOfSessionId: str = ""
    retrySourceTaskId: str = ""
    formalRetry: bool = False
    status: str
    turn: ResearchProjectAgentTaskTurnResponse
    resultRefs: list[str] = Field(default_factory=list)
    failureCode: str = ""
    returnTo: str = ""
    returnLabel: str = ""
    createdAt: str = ""
    updatedAt: str = ""
    chatRoute: str


class ResearchProjectAgentTaskStartResponse(BaseModel):
    task: ResearchProjectAgentTaskResponse
    researchProjectId: str
    experimentName: str
    sessionId: str
    sessionTitle: str
    sessionAttempt: int = 1
    sessionCreated: bool = False
    retryOfSessionId: str = ""
    chatRoute: str
    idempotentReplay: bool = False


class ResearchProjectAgentTaskKindResponse(BaseModel):
    taskKind: str
    teamRole: str
    roleKey: str
    roleLabel: str
    title: str


class ResearchProjectAgentTaskStatusResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str
    researchProjectId: str
    experimentName: str
    tasks: list[ResearchProjectAgentTaskResponse] = Field(default_factory=list)
    activeTasks: list[ResearchProjectAgentTaskResponse] = Field(default_factory=list)
    supportedTaskKinds: list[ResearchProjectAgentTaskKindResponse] = Field(
        default_factory=list
    )
    updatedAt: str = ""


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
    researchProfileId: str = Field("", max_length=200)
    researchQuestion: str = Field("", max_length=4000)
    researchMode: str = Field("", max_length=80)
    experimentPurpose: dict[str, Any] = Field(default_factory=dict)
    experimentMethod: str = Field("", max_length=120)
    requestedAdapterId: str = Field("", max_length=200)
    objective: str = Field("", max_length=4000)
    constraints: list[str] = Field(default_factory=list, max_length=40)
    methodConfig: dict[str, Any] = Field(default_factory=dict)
    metricContract: dict[str, Any] = Field(default_factory=dict)
    decisionContract: dict[str, Any] = Field(default_factory=dict)
    artifactContract: dict[str, Any] = Field(default_factory=dict)
    reproducibilityContract: dict[str, Any] = Field(default_factory=dict)
    iterationContract: dict[str, Any] = Field(default_factory=dict)
    recommendation: dict[str, Any] = Field(default_factory=dict)
    revision: int = Field(1, ge=1)
    supersedesPlanId: str = Field("", max_length=200)
    notes: str = Field("", max_length=4000)


class ExperimentEngineeringProxyHypothesisPayload(BaseModel):
    title: str = Field("", max_length=240)
    hypothesis: str = Field("", max_length=4000)
    claimBoundary: str = Field("", max_length=2000)
    expectedBenefit: str = Field("", max_length=1000)
    expectedComputeCost: str = Field("", max_length=1000)
    createdByAgent: str = Field("", max_length=160)
    idempotencyKey: str = Field("", max_length=240)


class ExperimentHypothesisRevisionPayload(BaseModel):
    createdByAgent: str = Field("", max_length=160)
    idempotencyKey: str = Field("", max_length=240)


class ExperimentScientificHypothesisCompletionPayload(ExperimentPlanCreatePayload):
    idempotencyKey: str = Field("", max_length=240)


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


class ExperimentDesignFreezePayload(BaseModel):
    frozenByAgent: str = Field("", max_length=160)


class ExperimentHypothesisResumePayload(BaseModel):
    hypothesisCandidateId: str = Field("", max_length=160)


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


class ExperimentSmokeRunPayload(BaseModel):
    adapter: str = Field("", max_length=120)
    seed: int | None = Field(None)
    threshold: float | None = Field(None)
    recordedByAgent: str = Field("", max_length=160)


class ExperimentFullRunResultPayload(BaseModel):
    evidenceKind: str = Field("", max_length=80)
    executionId: str = Field("", max_length=200)
    preparationId: str = Field("", max_length=200)
    receiptId: str = Field("", max_length=200)
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


class ExperimentFullRunExecutionPayload(BaseModel):
    executionConfig: dict[str, Any] = Field(default_factory=dict)
    recordedByAgent: str = Field("", max_length=160)


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


class ChallengeQuestionOutputPayload(BaseModel):
    output: dict[str, Any]
    citationChecks: list[dict[str, Any]] = Field(default_factory=list, max_length=64)
    registeredBy: str = Field("", max_length=160)
    parentRunId: str = Field("", max_length=160)
    lineageRefs: list[str] = Field(default_factory=list, max_length=64)
    resultPackage: dict[str, Any] | None = None
    authorizedModelPolicySha256: str = Field("", max_length=64)


class ChallengeQuestionPublishPayload(ChallengeQuestionOutputPayload):
    researchProjectId: str = Field(..., min_length=1, max_length=160)
    questionId: str = Field(..., min_length=1, max_length=32)
    taskId: str = Field(..., min_length=1, max_length=160)
    turnId: str = Field(..., min_length=1, max_length=200)
    projectEvidenceId: str = Field(..., min_length=1, max_length=160)


class ChallengeQuestionReviewPayload(BaseModel):
    reviewer: str = Field(..., min_length=1, max_length=160)
    rationale: str = Field(..., min_length=1, max_length=4000)
    decisions: dict[str, str]


class ChallengeQuestionArtifactResponse(BaseModel):
    path: str
    sha256: str
    immutable: bool


class ChallengeQuestionResultPackageArtifactResponse(BaseModel):
    path: str
    canonicalHash: str
    idempotencyKey: str
    immutable: bool


class ChallengeQuestionRunDetailResponse(BaseModel):
    teamId: str
    questionId: str
    selectedRunId: str
    record: dict[str, Any]
    output: dict[str, Any]
    runs: list[dict[str, Any]]
    artifact: ChallengeQuestionArtifactResponse
    resultPackage: dict[str, Any] | None = None
    resultPackageArtifact: ChallengeQuestionResultPackageArtifactResponse | None = None


class CandidateGraphBuildPayload(BaseModel):
    title: str = Field("", max_length=240)
    createdByAgent: str = Field("", max_length=160)
    sourceQualityAgentId: str = Field("", max_length=160)
    curationMode: str = Field("", max_length=80)
    maxCandidates: int = Field(80, ge=1, le=200)
    forceReview: bool = False
    forceRebuild: bool = False


class KnowledgeIngestionPrecheckPayload(BaseModel):
    stewardAgentId: str = Field("", max_length=160)
    maxCandidates: int = Field(32, ge=1, le=200)
    targetDomain: str = Field("", max_length=240)
    notes: str = Field("", max_length=4000)


class KnowledgeCollectionIngestionPayload(BaseModel):
    runId: str = Field("", max_length=128)
    extractionAgentId: str = Field("", max_length=160)
    sourceQualityAgentId: str = Field("", max_length=160)
    candidateGraphAgentId: str = Field("", max_length=160)
    stewardAgentId: str = Field("", max_length=160)
    reviewerAgentId: str = Field("", max_length=160)
    knowledgeBaseId: str = Field("", max_length=128)
    targetDomain: str = Field("", max_length=240)
    maxCandidates: int = Field(80, ge=1, le=200)
    maxSearchBatches: int = Field(20, ge=0, le=100)
    maxQueriesPerBatch: int = Field(4, ge=1, le=50)
    maxResultsPerQuery: int = Field(3, ge=1, le=20)
    maxRecords: int = Field(500, ge=1, le=1000)
    forceReview: bool = False
    forceRebuild: bool = False
    autoCreateKnowledgeBase: bool = True
    autoSubmit: bool = False
    autoReviewSource: bool = False
    autoApprove: bool = False
    notifyStewardAgent: bool = True
    wakeStewardAgent: bool = True
    backgroundExecution: bool = False
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


class NeuroMechanismExtractPayload(BaseModel):
    paperNoteId: str = Field("", max_length=128)
    createdByAgent: str = Field("", max_length=160)
    modelId: str = Field("", max_length=160)
    excerpt: str = Field("", max_length=24000)


class MechanismMappingPayload(BaseModel):
    mechanismId: str = Field("", max_length=128)
    createdByAgent: str = Field("", max_length=160)
    modelId: str = Field("", max_length=160)
    excerpt: str = Field("", max_length=24000)


class AlgorithmHypothesisPayload(BaseModel):
    mappingId: str = Field("", max_length=128)
    createdByAgent: str = Field("", max_length=160)
    modelId: str = Field("", max_length=160)
    excerpt: str = Field("", max_length=24000)


class ResearchReviewDecidePayload(BaseModel):
    candidateIds: list[str] = Field(default_factory=list, max_length=24)
    reviewedByAgent: str = Field("", max_length=160)
    decision: str = Field("", max_length=40)
    comments: str = Field("", max_length=4000)
    requiredChanges: list[str] = Field(default_factory=list, max_length=24)


class IterationProposePayload(BaseModel):
    parentCandidateId: str = Field("", max_length=128)
    action: str = Field("", max_length=40)
    changeReason: str = Field("", max_length=2000)
    mergeWithCandidateId: str = Field("", max_length=128)
    proposedByAgent: str = Field("", max_length=160)
    evidenceRefs: list[dict[str, Any]] = Field(default_factory=list, max_length=24)


class DeliverableExportPayload(BaseModel):
    requestedByAgent: str = Field("", max_length=160)


class PrdValidatePayload(BaseModel):
    requestedByAgent: str = Field("", max_length=160)


class KnowledgeGraphSyncPayload(BaseModel):
    syncedByAgent: str = Field("", max_length=160)
    force: bool = False


class KnowledgeGraphRollbackPayload(BaseModel):
    rolledBackByAgent: str = Field("", max_length=160)


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
