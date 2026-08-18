"""Public contracts for the Challenge Cup DEV platform control routes.

The service owns behavior and team storage resolution; these models only
declare the typed wire contract. Public JSON stays camelCase and the snapshot
never invents a parallel lifecycle.
"""

from __future__ import annotations

from typing import Any

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


class ChallengeCupDevBatchProjectionResponse(BaseModel):
    schemaVersion: int = 1
    planId: str = ""
    gateId: str = ""
    questionCount: int = 0
    statusSummary: dict[str, int] = Field(default_factory=dict)
    pendingCount: int = 0
    succeededCount: int = 0
    failedCount: int = 0
    blockedCount: int = 0
    totalAttempts: int = 0
    completedQuestionIds: list[str] = Field(default_factory=list)
    pendingQuestionIds: list[str] = Field(default_factory=list)
    lastUpdatedAt: str = ""
    canResume: bool = False


class ChallengeCupDevControlSnapshotResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    generatedAt: str = ""
    mode: str = "dev"
    realCampaignAllowed: bool = False
    nextLegalAction: str = ""
    report: ChallengeCupDevReadinessProjectionResponse | None = None
    batches: dict[str, ChallengeCupDevBatchProjectionResponse] = Field(default_factory=dict)
    boundary: dict[str, Any] = Field(default_factory=dict)


class ChallengeCupDevReadinessRunRequest(BaseModel):
    mode: str = Field("dev", min_length=1, max_length=16)


class ChallengeCupDevReadinessRunResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    report: ChallengeCupDevReadinessProjectionResponse
    cleanedUp: bool = True
    updatedAt: str = ""


class ChallengeCupDevBatchRunRequest(BaseModel):
    maxItems: int | None = Field(None, ge=0, le=MAX_DEV_BATCH_MAX_ITEMS)


class ChallengeCupDevBatchRunResponse(BaseModel):
    schemaVersion: int = 1
    teamId: str = ""
    planId: str = ""
    gateId: str = ""
    attempted: list[str] = Field(default_factory=list)
    outcomes: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint: ChallengeCupDevBatchProjectionResponse
    persistedAt: str = ""
    persisted: bool = True