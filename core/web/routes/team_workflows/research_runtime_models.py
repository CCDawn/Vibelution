"""Public JSON envelopes for research workflow runtime routes.

Read-only snapshots and catalog views publish stable top-level fields.
Binding config, run creation, and command receipts declare identifiers that
exist on every successful shape. Routes must use
response_model_exclude_unset=True. SSE stays on StreamingResponse.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ResearchRuntimeJsonResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class ResearchWorkflowDefinitionResponse(ResearchRuntimeJsonResponse):
    workflowId: str = ""
    workflowVersionId: str = ""
    definition: dict[str, Any] = Field(default_factory=dict)


class ResearchWorkflowRunListResponse(ResearchRuntimeJsonResponse):
    workflowId: str = ""
    runs: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowLaunchOptionsResponse(ResearchRuntimeJsonResponse):
    workflowId: str = ""
    teamId: str = ""
    questions: list[dict[str, Any]] = Field(default_factory=list)
    experiments: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowExperimentActivationResponse(ResearchRuntimeJsonResponse):
    experimentId: str = ""
    programId: str = ""
    themeId: str = ""
    campaignId: str = ""
    status: str = ""
    activatedBy: str = ""
    activatedAt: str = ""
    activationRef: str = ""
    scopeHash: str = ""
    activationHash: str = ""


class ResearchWorkflowEffectiveBindingsResponse(ResearchRuntimeJsonResponse):
    workflowId: str = ""
    workflowVersionId: str = ""
    teamId: str = ""
    bindings: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowBindingConfigResponse(ResearchRuntimeJsonResponse):
    workflowId: str = ""
    teamId: str = ""
    workflowDefaults: dict[str, Any] = Field(default_factory=dict)
    stageOverrides: dict[str, Any] = Field(default_factory=dict)
    nodeOverrides: dict[str, Any] = Field(default_factory=dict)
    updatedAt: str = ""


class ResearchWorkflowCreateRunResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    workflowId: str = ""
    workflowVersionId: str = ""
    teamId: str = ""
    projectId: str = ""
    questionId: str = ""
    runVersion: int = 0
    status: str = ""


class ResearchWorkflowRunSnapshotResponse(ResearchRuntimeJsonResponse):
    run: dict[str, Any] = Field(default_factory=dict)
    definition: dict[str, Any] = Field(default_factory=dict)
    nodeAttempts: dict[str, Any] = Field(default_factory=dict)
    activeNodeIds: list[str] = Field(default_factory=list)
    pendingHumanTasks: list[dict[str, Any]] = Field(default_factory=list)
    commandOffers: list[dict[str, Any]] = Field(default_factory=list)
    handoffSummary: dict[str, Any] = Field(default_factory=dict)
    agentBindingSummary: dict[str, Any] = Field(default_factory=dict)
    budgetSummary: dict[str, Any] = Field(default_factory=dict)
    latestEventSequence: int = 0
    generatedAt: str = ""


class ResearchWorkflowNodeDetailResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    nodeId: str = ""
    runVersion: int = 0
    actorKind: str = ""
    primaryRoleKey: str = ""
    label: str = ""
    runtimeCurrent: bool = False
    status: str | None = None
    bindingSnapshotId: str | None = None
    latestAttempt: dict[str, Any] | None = None
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    commandOffers: list[dict[str, Any]] = Field(default_factory=list)
    latestEventSequence: int = 0
    generatedAt: str = ""
    agentId: str | None = None
    displayName: str = ""
    resolvedFrom: str = ""
    sessionId: str | None = None
    taskId: str | None = None
    turnId: str | None = None
    sessionAttempt: int | None = None
    chatDeepLink: str | None = None
    sessionAnchorDegraded: bool = False
    rootSession: dict[str, Any] | None = None
    scopedSessions: list[dict[str, Any]] = Field(default_factory=list)
    blockedReason: str = ""
    nodeAttempt: int = 0


class ResearchWorkflowEventPageResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    latestEventSequence: int = 0
    afterSequence: int = 0
    lastReturnedSequence: int = 0
    hasMore: bool = False
    nextAfterSequence: int | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowHandoffListResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    handoffs: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowLedgerResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    projectId: str = ""
    claimEvidence: list[dict[str, Any]] = Field(default_factory=list)
    teamKnowledge: list[dict[str, Any]] = Field(default_factory=list)
    experimentPlanning: dict[str, Any] = Field(default_factory=dict)
    nodeRuns: list[dict[str, Any]] = Field(default_factory=list)
    handoffs: list[dict[str, Any]] = Field(default_factory=list)
    artifactManifests: list[dict[str, Any]] = Field(default_factory=list)
    resultPackage: dict[str, Any] | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    boundaries: dict[str, Any] = Field(default_factory=dict)
    graph: dict[str, Any] = Field(default_factory=dict)


class ResearchWorkflowBudgetResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    budgetLedgers: list[dict[str, Any]] = Field(default_factory=list)
    budgetReservations: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowHypothesisListResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    hypothesisPortfolios: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowCampaignListResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    experimentCampaigns: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowEvaluationResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    competitionEvaluations: list[dict[str, Any]] = Field(default_factory=list)
    qualityGateEvaluations: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowQuestionLineageResponse(ResearchRuntimeJsonResponse):
    schemaVersion: int = 0
    teamId: str = ""
    questionId: str = ""
    workflowRunId: str = ""
    roundId: str = ""
    degradedSegments: list[str] = Field(default_factory=list)
    segments: dict[str, Any] = Field(default_factory=dict)


class ResearchWorkflowHandoffDetailResponse(ResearchRuntimeJsonResponse):
    runId: str = ""
    teamId: str = ""
    runVersion: int = 0
    handoff: dict[str, Any] = Field(default_factory=dict)
    fromNodeRun: dict[str, Any] | None = None
    toNodeRun: dict[str, Any] | None = None
    humanTask: dict[str, Any] | None = None
    artifactManifests: list[dict[str, Any]] = Field(default_factory=list)


class ResearchWorkflowCommandReceiptResponse(ResearchRuntimeJsonResponse):
    commandId: str = ""
    runId: str = ""
    status: str = ""
    acceptedRunVersion: int | None = None
    idempotencyKey: str = ""
    latestEventSequence: int = 0
    problem: Any | None = None
    result: dict[str, Any] | None = None
