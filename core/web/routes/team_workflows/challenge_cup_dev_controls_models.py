"""Public contracts for the Challenge Cup DEV platform control routes.

The service owns behavior and team storage resolution; these models only
declare the typed wire contract. Public JSON stays camelCase, every nested
payload is an explicit typed model, and the snapshot never invents a parallel
lifecycle.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.research.competition.dev_control_batch import MAX_DEV_BATCH_MAX_ITEMS


class ChallengeCupDevGateResponse(BaseModel):
    gateId: str = ""
    status: str = ""
    detail: str = ""


class ChallengeCupDevReadinessProjectionResponse(BaseModel):
    schemaVersion: int = 1
    reportKind: str = ""
    status: str = ""
    mode: str = "dev"
    realCampaignAllowed: bool = False
    researchAuthorizationRequired: bool = True
    nextLegalAction: str = ""
    generatedAt: str = ""
    updatedAt: str = ""
    gates: list[ChallengeCupDevGateResponse] = Field(default_factory=list)


class ChallengeCupDevStatusSummaryResponse(BaseModel):
    pending: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0


class ChallengeCupDevBatchProjectionResponse(BaseModel):
    schemaVersion: int = 1
    planId: str = ""
    gateId: str = ""
    questionCount: int = 0
    statusSummary: ChallengeCupDevStatusSummaryResponse = Field(
        default_factory=ChallengeCupDevStatusSummaryResponse
    )
    pendingCount: int = 0
    succeededCount: int = 0
    failedCount: int = 0
    blockedCount: int = 0
    totalAttempts: int = 0
    completedQuestionIds: list[str] = Field(default_factory=list)
    pendingQuestionIds: list[str] = Field(default_factory=list)
    lastUpdatedAt: str = ""
    canResume: bool = False


class ChallengeCupDevBoundaryResponse(BaseModel):
    mode: str = "dev"
    realCampaignAllowed: bool = False
    authorizedPlans: list[str] = Field(default_factory=list)
    forbiddenPlans: list[str] = Field(default_factory=list)
    forbiddenFeatures: list[str] = Field(default_factory=list)
    fixtureOnly: bool = True


class ChallengeCupDevControlSnapshotResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    generatedAt: str = ""
    mode: str = "dev"
    realCampaignAllowed: bool = False
    nextLegalAction: str = ""
    report: ChallengeCupDevReadinessProjectionResponse | None = None
    batches: dict[str, ChallengeCupDevBatchProjectionResponse] = Field(default_factory=dict)
    boundary: ChallengeCupDevBoundaryResponse = Field(
        default_factory=ChallengeCupDevBoundaryResponse
    )


class ChallengeCupDevReadinessRunRequest(BaseModel):
    mode: str = Field("dev", min_length=1, max_length=16)


class ChallengeCupDevReadinessRunResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    report: ChallengeCupDevReadinessProjectionResponse
    cleanedUp: Literal[True]
    updatedAt: str = ""


class ChallengeCupDevBatchRunRequest(BaseModel):
    maxItems: int | None = Field(None, ge=0, le=MAX_DEV_BATCH_MAX_ITEMS)
    retryFailed: bool = False


class ChallengeCupDevBatchOutcomeResponse(BaseModel):
    questionId: str = ""
    outcome: str = ""


class ChallengeCupDevBatchRunResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    planId: str = ""
    gateId: str = ""
    attempted: list[str] = Field(default_factory=list)
    outcomes: list[ChallengeCupDevBatchOutcomeResponse] = Field(default_factory=list)
    checkpoint: ChallengeCupDevBatchProjectionResponse
    persistedAt: str = ""
    persisted: Literal[True]


class ChallengeCupCatalogBlockerResponse(BaseModel):
    code: str = ""
    message: str = ""
    remediationLabel: str = ""


class ChallengeCupCatalogCountsResponse(BaseModel):
    queued: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0


class ChallengeCupCatalogQuestionResponse(BaseModel):
    questionId: str = ""
    title: str = ""
    domain: str = ""
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    executionStatus: str = "pending"
    currentStage: str = ""
    checkpointProgress: str = "0/1"
    attempts: int = 0
    planId: str = ""
    action: Literal["continue", "retry", "view"] = "view"
    blocker: ChallengeCupCatalogBlockerResponse | None = None


class ChallengeCupCatalogOverviewResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    generatedAt: str = ""
    questionCount: int = 0
    counts: ChallengeCupCatalogCountsResponse = Field(
        default_factory=ChallengeCupCatalogCountsResponse
    )
    questions: list[ChallengeCupCatalogQuestionResponse] = Field(default_factory=list)


class ChallengeCupTokenUsageTotalsResponse(BaseModel):
    totalTokens: int = 0
    callCount: int = 0
    inputTokens: int = 0
    outputTokens: int = 0


class ChallengeCupTokenUsageStageResponse(BaseModel):
    stageId: str = ""
    totalTokens: int = 0
    callCount: int = 0


class ChallengeCupTokenUsageAnomalyResponse(BaseModel):
    stageId: str = ""
    message: str = ""


class ChallengeCupTokenUsageQuestionResponse(BaseModel):
    questionId: str = ""
    totalTokens: int = 0
    callCount: int = 0
    inputTokens: int = 0
    outputTokens: int = 0
    stages: list[ChallengeCupTokenUsageStageResponse] = Field(default_factory=list)
    anomaly: ChallengeCupTokenUsageAnomalyResponse | None = None


class ChallengeCupTokenUsageResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    generatedAt: str = ""
    unit: Literal["tokens"] = "tokens"
    priced: Literal[False] = False
    program: ChallengeCupTokenUsageTotalsResponse = Field(
        default_factory=ChallengeCupTokenUsageTotalsResponse
    )
    questions: list[ChallengeCupTokenUsageQuestionResponse] = Field(default_factory=list)