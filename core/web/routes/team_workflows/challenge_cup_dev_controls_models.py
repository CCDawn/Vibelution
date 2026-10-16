"""Public contracts for the Challenge Cup DEV platform control routes.

The service owns behavior and team storage resolution; these models only
declare the typed wire contract for the read-only catalog overview and token
usage projections. Public JSON stays camelCase and every nested payload is an
explicit typed model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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