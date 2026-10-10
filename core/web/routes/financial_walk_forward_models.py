"""Typed transport for frozen train/select/test workflows."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr


class WalkForwardCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidateId: StrictStr = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    maxPositionPct: StrictInt = Field(ge=0, le=100)


class WalkForwardPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trainSessions: StrictInt = Field(default=126, ge=2, le=2500)
    testSessions: StrictInt = Field(default=63, ge=2, le=1250)
    stepSessions: StrictInt = Field(default=63, ge=2, le=1250)
    candidates: list[WalkForwardCandidate] = Field(min_length=2, max_length=4)
    maxTokens: StrictInt = Field(default=2_000_000, ge=512, le=2_000_000)


class WalkForwardMetrics(BaseModel):
    totalReturnPct: float | None = None
    benchmarkReturnPct: float | None = None
    excessReturnPct: float | None = None
    maxDrawdownPct: float | None = None


class WalkForwardFold(BaseModel):
    foldId: str
    trainStart: str
    trainEnd: str
    testStart: str
    testEnd: str
    selectedCandidateId: str | None = None
    testRunId: str | None = None
    status: str
    metrics: WalkForwardMetrics | None = None


class WalkForwardWorkflow(BaseModel):
    agentId: str
    workflowId: str
    sourceRunId: str
    status: Literal["preview", "queued", "running", "stop_requested", "stopped", "paused_unknown", "completed", "failed", "blocked"]
    planHash: str
    trainSessions: int
    testSessions: int
    stepSessions: int
    maxTokens: int
    estimatedTokens: int
    tokensUsed: int = 0
    budgetTokensCommitted: int = 0
    tokenUsageEstimated: bool = False
    candidates: list[WalkForwardCandidate]
    folds: list[WalkForwardFold]
    activeRunId: str | None = None
    terminalReason: str | None = None
    createdAt: str
    updatedAt: str
    notice: str


class WalkForwardPage(BaseModel):
    items: list[WalkForwardWorkflow]
