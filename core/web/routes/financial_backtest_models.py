"""Public HTTP contracts for bounded, point-in-time AI backtests."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


class FinancialBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: StrictStr = Field(min_length=1, max_length=24)
    startDate: StrictStr = Field(min_length=10, max_length=10)
    endDate: StrictStr = Field(min_length=10, max_length=10)
    strategy: StrictStr = Field(min_length=1, max_length=4_000)
    initialCash: StrictFloat | StrictInt = Field(default=100_000, ge=1_000, le=100_000_000, allow_inf_nan=False)
    maxPositionPct: StrictFloat | StrictInt = Field(default=100, ge=0, le=100, allow_inf_nan=False)
    decisionInterval: StrictInt = Field(default=5, ge=1, le=252)
    commissionBps: StrictFloat | StrictInt = Field(default=3, ge=0, le=100, allow_inf_nan=False)
    minimumCommission: StrictFloat | StrictInt = Field(default=5, ge=0, le=10_000, allow_inf_nan=False)
    slippageBps: StrictFloat | StrictInt = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    maxDecisions: StrictInt = Field(default=500, ge=1, le=500)
    maxTokens: StrictInt = Field(default=500_000, ge=512, le=2_000_000)
    modelId: StrictStr | None = Field(default=None, max_length=160)


class FinancialBacktestPreviewRequest(FinancialBacktestRequest):
    pass


class FinancialBacktestStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clientRequestId: StrictStr = Field(min_length=36, max_length=36)
    previewId: StrictStr = Field(min_length=36, max_length=36)


class FinancialBacktestResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retryUnknownDecisionDate: StrictStr | None = Field(default=None, min_length=10, max_length=10)
    confirmPossibleDuplicateCharge: bool = False


class FinancialBacktestExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["json", "csv"]


class ProviderWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    startDate: str
    endDate: str
    rawBars: int
    qfqBars: int
    calendarBars: int = 0


class FinancialBacktestCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requestedStartDate: str
    requestedEndDate: str
    actualStartDate: str | None
    actualEndDate: str | None
    availableStartDate: str | None
    availableEndDate: str | None
    tradingDays: int
    warmupBars: int
    providerWindows: list[ProviderWindow]
    complete: bool
    tradingCalendarStatus: str = "unverified"
    calendarSymbol: str = "sh000001"


class FinancialBacktestParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    initialCash: float
    maxPositionPct: float = Field(ge=0, le=100, description="仓位百分比，0到100")
    decisionInterval: int
    commissionBps: float
    minimumCommission: float
    slippageBps: float
    maxDecisions: int
    maxTokens: int


class FinancialBacktestPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    previewId: str
    expiresAt: str
    symbol: str
    dateCoverage: FinancialBacktestCoverage
    decisionSchedule: list[str]
    decisionCount: int
    maxDecisions: int
    maxTokens: int
    estimatedTokens: int
    reservedOutputTokens: int
    modelId: str
    modelConfigHash: str = ""
    paramsHash: str
    dataHash: str
    actionsStatus: Literal["clear", "factor_check_passed", "blocked", "unavailable"]
    actionDates: list[str]
    canStart: bool
    blockReason: str | None
    warnings: list[str]
    source: str
    sourceUrl: str
    fetchedAt: str
    adjustment: str
    notice: str
    params: FinancialBacktestParams


class FinancialBacktestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    targetWeight: float = Field(ge=0, le=100, description="AI目标仓位百分比，0到maxPositionPct")
    reason: str = Field(min_length=1, max_length=2_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    modelId: str
    inputHash: str
    decisionHash: str
    attempts: int = 1
    tokens: int = 0


class FinancialBacktestEquityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    equity: float
    benchmarkEquity: float
    cash: float
    shares: int
    units: int
    marketValue: float
    benchmarkCash: float
    benchmarkShares: int


class FinancialBacktestTrade(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signalDate: str
    date: str
    side: Literal["buy", "sell"]
    price: float
    units: int
    shares: int
    fee: float
    commission: float
    stampDuty: float
    slippageCost: float
    notional: float
    tPlusOne: bool


class FinancialBacktestOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signalDate: str
    date: str
    side: Literal["buy", "sell", "hold"]
    status: Literal["filled", "rejected", "no_action"]
    reason: str
    requestedShares: int
    filledShares: int
    units: int
    price: float | None
    notional: float
    commission: float
    stampDuty: float
    fee: float
    slippageCost: float
    tPlusOne: bool
    limitStatus: str


class FinancialBacktestRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    symbol: str
    status: Literal["queued", "running", "stop_requested", "stopped", "paused_unknown", "completed", "failed", "blocked"]
    createdAt: str
    updatedAt: str
    startedAt: str | None
    completedAt: str | None
    decisionCount: int
    completedDecisionCount: int
    progress: float
    modelId: str
    paramsHash: str
    dataHash: str
    totalReturnPct: float | None = None
    maxDrawdownPct: float | None = None
    terminalReason: str | None = None


class FinancialBacktestRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    items: list[FinancialBacktestRunSummary]
    nextCursor: str | None
    limit: int


class FinancialBacktestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    clientRequestId: str
    symbol: str
    status: Literal["queued", "running", "stop_requested", "stopped", "paused_unknown", "completed", "failed", "blocked"]
    progress: float
    currentDecisionDate: str | None
    decisionCount: int
    completedDecisionCount: int
    callsUsed: int
    tokensUsed: int
    estimatedTokens: int
    tokensReserved: int
    maxTokens: int
    modelId: str
    modelConfigHash: str = ""
    paramsHash: str
    dataHash: str
    params: FinancialBacktestParams
    dateCoverage: FinancialBacktestCoverage
    actionsStatus: Literal["clear", "factor_check_passed", "blocked", "unavailable"]
    actionDates: list[str]
    source: str
    sourceUrl: str
    fetchedAt: str
    adjustment: str
    notice: str
    warnings: list[str]
    decisions: list[FinancialBacktestDecision]
    metrics: dict[str, Any] | None
    equity: list[FinancialBacktestEquityPoint]
    trades: list[FinancialBacktestTrade]
    orders: list[FinancialBacktestOrder]
    benchmarkOrders: list[FinancialBacktestOrder] = Field(default_factory=list)
    startedAt: str | None
    updatedAt: str
    completedAt: str | None
    terminalReason: str | None
    errorCode: str | None
    uncertainDecisionDate: str | None
    tokenAccounting: Literal["measured", "estimated", "reserved"]


class FinancialBacktestExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    format: Literal["json", "csv"]
    fileName: str
    mediaType: str
    encoding: Literal["utf8", "base64"]
    content: str
