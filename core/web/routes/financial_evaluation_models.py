"""Public contracts for research outcome checks and deterministic backtests."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    clientRequestId: str = Field(min_length=36, max_length=36)
    sessionId: str = Field(min_length=1, max_length=160)
    turnId: str = Field(min_length=1, max_length=160)
    symbol: str = Field(min_length=1, max_length=24)
    dueDate: str = Field(min_length=10, max_length=10)
    direction: Literal["up", "down"]
    thresholdPct: float = Field(ge=0, le=100, allow_inf_nan=False, strict=True)
    claimText: str = Field(min_length=1, max_length=500)


class LessonRef(BaseModel):
    type: str
    id: str


class LessonRecord(BaseModel):
    id: str
    text: str
    createdAt: str
    refs: list[LessonRef] = Field(default_factory=list)


class ClaimEvidence(BaseModel):
    baseDate: str
    baseClose: float
    dueDateQuoteDate: str
    dueClose: float
    returnPct: float
    sourceUrl: str
    fetchedAt: str
    seriesHash: str


class ClaimError(BaseModel):
    code: str
    unavailableReason: str


class ClaimRecord(BaseModel):
    id: str
    agentId: str
    sessionId: str
    turnId: str
    symbol: str
    analysisDate: str
    dueDate: str
    direction: Literal["up", "down"]
    thresholdPct: float
    claimText: str
    status: Literal["pending", "due", "verified", "unverifiable"]
    registeredBeforeDue: bool
    retrospective: bool
    outcome: Literal["hit", "miss"] | None
    checkedAt: str | None
    revision: int
    evidence: ClaimEvidence | None
    error: ClaimError | None
    lesson: LessonRecord | None


class ClaimPage(BaseModel):
    agentId: str
    items: list[ClaimRecord]
    limit: int


class FeedbackPrompt(BaseModel):
    id: str
    text: str


class LessonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=500)
    clientRequestId: str = Field(min_length=36, max_length=36)


class ReflectionContext(BaseModel):
    items: list[LessonRecord]


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1, max_length=24)
    startDate: str = Field(min_length=10, max_length=10)
    endDate: str = Field(min_length=10, max_length=10)
    window: int = Field(default=20, ge=5, le=60, strict=True)
    commissionBps: float = Field(default=3, ge=0, le=100, allow_inf_nan=False, strict=True)
    slippageBps: float = Field(default=5, ge=0, le=100, allow_inf_nan=False, strict=True)


class BacktestMetrics(BaseModel):
    totalReturnPct: float
    benchmarkReturnPct: float
    excessReturnPct: float
    maxDrawdownPct: float
    tradeCount: int
    fees: float


class EquityPoint(BaseModel):
    date: str
    equity: float
    benchmarkEquity: float


class BacktestTrade(BaseModel):
    signalDate: str
    date: str
    side: Literal["buy", "sell"]
    price: float
    units: float
    fee: float


class BacktestResult(BaseModel):
    symbol: str
    startDate: str
    endDate: str
    window: int
    metrics: BacktestMetrics
    equity: list[EquityPoint]
    trades: list[BacktestTrade]
    source: str
    sourceUrl: str
    fetchedAt: str
    adjustment: str
    dataHash: str
    notice: str
