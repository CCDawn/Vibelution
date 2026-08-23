"""Public contracts for the Challenge Cup real catalog batch routes.

The service owns behavior, authorization and team storage resolution; these
models only declare the typed wire contract. Public JSON stays camelCase and
never exposes the internal checkpoint or raw run ledger rows.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from core.research.competition.real_control_batch import (
    DEFAULT_REAL_FAILURE_BUDGET,
)


class ChallengeCupRealBatchStartRequest(BaseModel):
    confirmed: bool = False
    concurrency: int | None = None
    maxItems: int | None = None
    failureBudget: int | None = None


class ChallengeCupRealBatchAuthorizationRequest(BaseModel):
    """The server derives identity, readiness evidence, and batch scope."""

    model_config = {"extra": "forbid"}


class ChallengeCupRealBatchAuthorizationResponse(BaseModel):
    authorizationId: str = ""
    teamId: str = ""
    planId: str = ""
    batchScope: dict[str, Any] = Field(default_factory=dict)
    scopeHash: str = ""
    approvedBy: str = ""
    approvedAtMs: int = 0
    readinessReportSha256: str = ""
    recordHash: str = ""
    createdAtMs: int = 0


class ChallengeCupRealBatchCancelRequest(BaseModel):
    confirmed: bool = False


class ChallengeCupRealBatchRunRefResponse(BaseModel):
    runId: str = ""
    attempt: int = 0


class ChallengeCupRealBatchStatusSummaryResponse(BaseModel):
    pending: int = 0
    running: int = 0
    succeeded: int = 0
    failed: int = 0
    blocked: int = 0


class ChallengeCupRealBatchProjectionResponse(BaseModel):
    schemaVersion: int = 1
    planId: str = ""
    gateId: str = ""
    exists: bool = True
    questionCount: int = 0
    statusSummary: ChallengeCupRealBatchStatusSummaryResponse = Field(
        default_factory=ChallengeCupRealBatchStatusSummaryResponse
    )
    pendingCount: int = 0
    succeededCount: int = 0
    failedCount: int = 0
    blockedCount: int = 0
    totalAttempts: int = 0
    completedQuestionIds: list[str] = Field(default_factory=list)
    pendingQuestionIds: list[str] = Field(default_factory=list)
    runRefs: dict[str, ChallengeCupRealBatchRunRefResponse] = Field(default_factory=dict)
    awaitingApprovalQuestionIds: list[str] = Field(default_factory=list)
    consecutiveFailures: int = 0
    failureBudget: int = DEFAULT_REAL_FAILURE_BUDGET
    circuitBreakerOpen: bool = False
    cancelled: bool = False
    gateComplete: bool = False
    lastUpdatedAt: str = ""
    canResume: bool = False


class ChallengeCupRealBatchOutcomeItemResponse(BaseModel):
    questionId: str = ""
    outcome: str = ""


class ChallengeCupRealBatchStartResponse(ChallengeCupRealBatchProjectionResponse):
    launched: list[ChallengeCupRealBatchOutcomeItemResponse] = Field(default_factory=list)


class ChallengeCupRealBatchPollResponse(ChallengeCupRealBatchProjectionResponse):
    harvested: list[ChallengeCupRealBatchOutcomeItemResponse] = Field(default_factory=list)
    launched: list[ChallengeCupRealBatchOutcomeItemResponse] = Field(default_factory=list)
