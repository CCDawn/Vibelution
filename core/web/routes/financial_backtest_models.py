"""Public HTTP contracts for bounded, point-in-time AI backtests."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)


class FinancialBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: StrictStr | None = Field(default=None, min_length=1, max_length=24)
    symbols: list[StrictStr] | None = Field(default=None, min_length=1, max_length=10)
    startDate: StrictStr = Field(min_length=10, max_length=10)
    endDate: StrictStr = Field(min_length=10, max_length=10)
    outOfSampleStartDate: StrictStr | None = Field(default=None, min_length=10, max_length=10)
    strategy: StrictStr = Field(min_length=1, max_length=4_000)
    initialCash: StrictFloat | StrictInt = Field(default=100_000, ge=1_000, le=100_000_000, allow_inf_nan=False)
    maxPositionPct: StrictFloat | StrictInt = Field(default=100, ge=0, le=100, allow_inf_nan=False)
    maxParticipationPct: StrictFloat | StrictInt = Field(default=1, ge=0.1, le=100, allow_inf_nan=False)
    quantityRuleVersion: Literal["ashare_quantity_v2", "legacy_100_v1"] = "ashare_quantity_v2"
    decisionInterval: StrictInt = Field(default=5, ge=1, le=252)
    commissionBps: StrictFloat | StrictInt = Field(default=3, ge=0, le=100, allow_inf_nan=False)
    minimumCommission: StrictFloat | StrictInt = Field(default=5, ge=0, le=10_000, allow_inf_nan=False)
    slippageBps: StrictFloat | StrictInt = Field(default=5, ge=0, le=100, allow_inf_nan=False)
    maxDecisions: StrictInt = Field(default=500, ge=1, le=500)
    maxTokens: StrictInt = Field(default=500_000, ge=512, le=2_000_000)
    modelId: StrictStr | None = Field(default=None, max_length=160)
    dataSource: Literal["tencent", "eastmoney", "sina", "auto"] = "tencent"
    corporateActionPolicy: Literal["block", "verified_cash_dividends"] = "block"
    researchInput: Literal["price_only", "announcements", "financial_reports"] = "price_only"

    @model_validator(mode="after")
    def require_one_symbol_selector(self) -> FinancialBacktestRequest:
        if bool(self.symbol) == bool(self.symbols):
            raise ValueError("请传入symbol或symbols其中一个字段")
        return self


class FinancialBacktestPreviewRequest(FinancialBacktestRequest):
    pass


class FinancialBacktestForkPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: StrictStr | None = Field(default=None, min_length=1, max_length=4_000)
    modelId: StrictStr | None = Field(default=None, max_length=160)
    maxTokens: StrictInt | None = Field(default=None, ge=512, le=2_000_000)
    maxPositionPct: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    decisionInterval: StrictInt | None = Field(default=None, ge=1, le=252)
    commissionBps: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    minimumCommission: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=10_000, allow_inf_nan=False)
    slippageBps: StrictFloat | StrictInt | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    maxParticipationPct: StrictFloat | StrictInt | None = Field(default=None, ge=0.1, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_one_parameter_override(self) -> FinancialBacktestForkPreviewRequest:
        parameter_fields = (
            "maxPositionPct",
            "decisionInterval",
            "commissionBps",
            "minimumCommission",
            "slippageBps",
            "maxParticipationPct",
        )
        selected = [key for key in parameter_fields if key in self.model_fields_set]
        if any(getattr(self, key) is None for key in selected):
            raise ValueError("回测参数覆盖值不能为空")
        if len(selected) > 1:
            raise ValueError("单次派生预览最多更改一项回测参数")
        return self


class FinancialBacktestCompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runIds: list[StrictStr] = Field(min_length=2, max_length=4)
    axis: Literal["strategy", "model", "parameter"]
    parameterKey: Literal[
        "maxPositionPct",
        "decisionInterval",
        "commissionBps",
        "minimumCommission",
        "slippageBps",
        "maxParticipationPct",
    ] | None = None

    @model_validator(mode="after")
    def require_unique_run_ids(self) -> FinancialBacktestCompareRequest:
        if len(set(self.runIds)) != len(self.runIds):
            raise ValueError("runIds不能重复")
        if self.axis == "parameter" and self.parameterKey is None:
            raise ValueError("参数比较必须指定parameterKey")
        if self.axis != "parameter" and self.parameterKey is not None:
            raise ValueError("策略或模型比较不能指定parameterKey")
        return self


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
    maxParticipationPct: float | None = Field(default=None, ge=0.1, le=100)
    quantityRuleVersion: Literal["ashare_quantity_v2", "legacy_100_v1"] | None = None
    corporateActionPolicy: Literal["block", "verified_cash_dividends"] | None = None
    decisionInterval: int
    commissionBps: float
    minimumCommission: float
    slippageBps: float
    maxDecisions: int
    maxTokens: int
    outOfSampleStartDate: str | None = None


class FinancialBacktestComparisonProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contractVersion: str
    commonParamsHash: str
    strategyHash: str
    sourceRunId: str | None = None


class FinancialBacktestResearchCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["available", "partial"]
    groupCount: int
    availableGroupCount: int
    partialGroupCount: int
    failedGroupCount: int
    itemCount: int
    notice: str
    warnings: list[str]


class FinancialBacktestActionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["complete"]
    ruleVersion: Literal["ashare_cash_dividend_v1"]
    artifactHash: str
    startDate: str
    endDate: str
    eventCount: int


class FinancialBacktestDividendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actionId: str
    noticeId: str
    publishedDate: str
    title: str
    sourceUrl: str
    pdfSha256: str
    recordDate: str
    exDate: str
    paymentDate: str
    cashPerShare: str
    recordCaptured: bool
    ledgerApplied: bool
    entitledShares: int
    grossAmount: str
    exRecognized: bool
    paymentComplete: bool
    taxPayable: str
    taxTotal: str
    taxPaid: str


class FinancialBacktestDividendLot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acquiredDate: str
    shares: int
    dividendRights: dict[str, int]


class FinancialBacktestDividendAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schemaVersion: Literal[1]
    ruleVersion: Literal["ashare_cash_dividend_v1"]
    artifactHash: str
    symbol: str
    settlementRounding: Literal["unverified_decimal_exact"]
    receivable: str
    taxPayable: str
    taxTotal: str
    dividendsTotal: str
    events: list[FinancialBacktestDividendEvent]
    lots: list[FinancialBacktestDividendLot]


class FinancialBacktestPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    previewId: str
    expiresAt: str
    symbol: str | None
    symbols: list[str] = Field(default_factory=list)
    dateCoverage: FinancialBacktestCoverage
    assetCoverage: dict[str, FinancialBacktestCoverage] = Field(default_factory=dict)
    assetDataHashes: dict[str, str] = Field(default_factory=dict)
    assetSources: dict[str, dict[str, str]] = Field(default_factory=dict)
    outOfSampleStartDate: str | None = None
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
    researchInput: Literal["price_only", "announcements", "financial_reports"] = "price_only"
    researchHash: str | None = None
    researchCoverage: FinancialBacktestResearchCoverage | None = None
    actionsStatus: Literal["clear", "factor_check_passed", "verified_cash_dividends", "blocked", "unavailable"]
    corporateActionCoverage: dict[str, FinancialBacktestActionCoverage] | None = None
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
    comparisonProvenance: FinancialBacktestComparisonProvenance


class FinancialBacktestDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    targetWeight: float | None = Field(default=None, ge=0, le=100, description="AI目标仓位百分比，0到maxPositionPct")
    targetWeights: dict[str, float] | None = None
    reason: str = Field(min_length=1, max_length=2_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    modelId: str
    inputHash: str
    decisionHash: str
    attempts: int = 1
    tokens: int = 0

    @model_validator(mode="after")
    def require_one_weight_shape(self) -> FinancialBacktestDecision:
        if (self.targetWeight is None) == (self.targetWeights is None):
            raise ValueError("决策必须且只能包含targetWeight或targetWeights")
        return self


class FinancialBacktestEquityPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str
    equity: float
    benchmarkEquity: float
    cash: float
    shares: int | None = None
    units: int | None = None
    marketValue: float | None = None
    benchmarkCash: float | None = None
    benchmarkShares: int | None = None
    positions: dict[str, int] | None = None
    marketValues: dict[str, float] | None = None
    sellablePositions: dict[str, int] | None = None
    benchmarkPositions: dict[str, int] | None = None
    dividendReceivable: float | None = None
    dividendTaxPayable: float | None = None
    benchmarkDividendReceivable: float | None = None
    benchmarkDividendTaxPayable: float | None = None


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
    symbol: str | None = None


class FinancialBacktestOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signalDate: str
    date: str
    side: Literal["buy", "sell", "hold"]
    status: Literal["filled", "partial_fill", "rejected", "no_action"]
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
    symbol: str | None = None


class FinancialBacktestExecutionFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    failure: Literal["insufficient_cash_for_dividend_tax"]
    date: str
    symbol: str
    availableCash: str
    dividendTaxDue: str
    projectedCashAfterTax: str
    order: FinancialBacktestOrder
    trade: FinancialBacktestTrade


class FinancialBacktestRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    symbol: str | None
    symbols: list[str] = Field(default_factory=list)
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
    comparisonProvenance: FinancialBacktestComparisonProvenance | None = None
    totalReturnPct: float | None = None
    maxDrawdownPct: float | None = None
    benchmarkStatus: Literal["invested", "partial_cash_sleeves", "cash_only"] | None = None
    unfilledBenchmarkSymbols: list[str] = Field(default_factory=list)
    terminalReason: str | None = None
    outOfSampleStartDate: str | None = None
    evaluation: dict[str, Any] | None = None


class FinancialBacktestRunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    items: list[FinancialBacktestRunSummary]
    nextCursor: str | None
    limit: int


class FinancialBacktestRobustnessMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    totalReturnPct: float
    benchmarkReturnPct: float
    excessReturnPct: float
    maxDrawdownPct: float
    fees: float
    tradeCount: int


class FinancialBacktestRobustnessWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    startDate: str
    endDate: str
    baselineDate: str | None
    tradingDays: int
    complete: bool | None
    metrics: FinancialBacktestRobustnessMetrics


class FinancialBacktestRobustness(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schemaVersion: Literal[1]
    status: Literal["available", "insufficient_sample", "unavailable"]
    scope: Literal["out_of_sample", "full_period"]
    windowSize: Literal[63]
    minCompleteWindows: Literal[4]
    completeWindowCount: int
    partialWindowCount: int
    outperformingWindowRatePct: float | None
    evaluatedStartDate: str | None
    evaluatedEndDate: str | None
    tradingDays: int
    annualWindows: list[FinancialBacktestRobustnessWindow]
    fixedWindows: list[FinancialBacktestRobustnessWindow]
    error: str | None
    notice: str


class FinancialBacktestAdvancedMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    totalReturnPct: StrictFloat | StrictInt | None = None
    benchmarkReturnPct: StrictFloat | StrictInt | None = None
    excessReturnPct: StrictFloat | StrictInt | None = None
    maxDrawdownPct: StrictFloat | StrictInt | None = None
    tradeCount: StrictInt | None = None
    fees: StrictFloat | StrictInt | None = None
    commissionFees: StrictFloat | StrictInt | None = None
    stampDuty: StrictFloat | StrictInt | None = None
    slippageCost: StrictFloat | StrictInt | None = None
    benchmarkFees: StrictFloat | StrictInt | None = None
    benchmarkSlippageCost: StrictFloat | StrictInt | None = None
    grossTurnover: StrictFloat | StrictInt | None = None


class FinancialBacktestCostScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    id: Literal["baseline", "cost_1_5x", "cost_2x"]
    status: Literal["available", "unavailable"]
    costMultiplier: StrictFloat | StrictInt
    commissionBps: StrictFloat | StrictInt
    minimumCommission: StrictFloat | StrictInt
    slippageBps: StrictFloat | StrictInt
    metrics: FinancialBacktestAdvancedMetrics | None
    outOfSampleMetrics: FinancialBacktestAdvancedMetrics | None
    error: str | None


class FinancialBacktestCostStress(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["available", "partial", "unavailable"]
    scenarios: list[FinancialBacktestCostScenario]
    error: str | None = None
    notice: str


class FinancialBacktestReturnUncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    status: Literal["available", "insufficient_sample", "unavailable"]
    method: Literal["newey_west_hac"]
    metric: Literal["annualized_log_excess_return_pct"]
    confidenceLevel: StrictFloat | StrictInt
    observations: StrictInt
    lag: StrictInt | None
    pointEstimatePct: StrictFloat | StrictInt | None
    lowerPct: StrictFloat | StrictInt | None
    upperPct: StrictFloat | StrictInt | None
    error: str | None
    notice: str


class FinancialBacktestAdvancedEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    schemaVersion: Literal[1]
    basis: Literal["frozen_decisions"]
    status: Literal["available", "unavailable"]
    outOfSampleStartDate: str | None
    costStress: FinancialBacktestCostStress
    returnUncertainty: FinancialBacktestReturnUncertainty
    error: str | None = None
    notice: str


class FinancialBacktestRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    clientRequestId: str
    symbol: str | None
    symbols: list[str] = Field(default_factory=list)
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
    researchInput: Literal["price_only", "announcements", "financial_reports"] = "price_only"
    researchHash: str | None = None
    researchCoverage: FinancialBacktestResearchCoverage | None = None
    comparisonProvenance: FinancialBacktestComparisonProvenance | None = None
    params: FinancialBacktestParams
    dateCoverage: FinancialBacktestCoverage
    assetCoverage: dict[str, FinancialBacktestCoverage] = Field(default_factory=dict)
    assetDataHashes: dict[str, str] = Field(default_factory=dict)
    assetSources: dict[str, dict[str, str]] = Field(default_factory=dict)
    outOfSampleStartDate: str | None = None
    actionsStatus: Literal["clear", "factor_check_passed", "verified_cash_dividends", "blocked", "unavailable"]
    corporateActionCoverage: dict[str, FinancialBacktestActionCoverage] | None = None
    dividendAccounting: FinancialBacktestDividendAudit | dict[str, FinancialBacktestDividendAudit] | None = None
    benchmarkDividendAccounting: FinancialBacktestDividendAudit | dict[str, FinancialBacktestDividendAudit] | None = None
    actionDates: list[str]
    source: str
    sourceUrl: str
    fetchedAt: str
    adjustment: str
    notice: str
    warnings: list[str]
    decisions: list[FinancialBacktestDecision]
    metrics: dict[str, Any] | None
    evaluation: dict[str, Any] | None = None
    robustness: FinancialBacktestRobustness | None = None
    advancedEvaluation: FinancialBacktestAdvancedEvaluation | None = None
    equity: list[FinancialBacktestEquityPoint]
    trades: list[FinancialBacktestTrade]
    orders: list[FinancialBacktestOrder]
    benchmarkOrders: list[FinancialBacktestOrder] = Field(default_factory=list)
    benchmarkStatus: Literal["invested", "partial_cash_sleeves", "cash_only"] | None = None
    unfilledBenchmarkSymbols: list[str] = Field(default_factory=list)
    startedAt: str | None
    updatedAt: str
    completedAt: str | None
    terminalReason: str | None
    errorCode: str | None
    executionFailure: FinancialBacktestExecutionFailure | None = None
    uncertainDecisionDate: str | None
    tokenAccounting: Literal["measured", "estimated", "reserved"]


class FinancialBacktestComparisonReason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    runIds: list[str]
    message: str


class FinancialBacktestComparisonMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totalReturnPct: StrictFloat | StrictInt | None = None
    benchmarkReturnPct: StrictFloat | StrictInt | None = None
    excessReturnPct: StrictFloat | StrictInt | None = None
    annualizedReturnPct: StrictFloat | StrictInt | None = None
    benchmarkAnnualizedReturnPct: StrictFloat | StrictInt | None = None
    maxDrawdownPct: StrictFloat | StrictInt | None = None
    maxDrawdownSessions: StrictInt | None = None
    volatilityAnnualizedPct: StrictFloat | StrictInt | None = None
    sharpeRatio: StrictFloat | StrictInt | None = None
    benchmarkMaxDrawdownPct: StrictFloat | StrictInt | None = None
    tradeCount: StrictInt | None = None
    closedTradeCount: StrictInt | None = None
    winningTradeCount: StrictInt | None = None
    winRatePct: StrictFloat | StrictInt | None = None
    grossTurnover: StrictFloat | StrictInt | None = None
    fees: StrictFloat | StrictInt | None = None
    commissionFees: StrictFloat | StrictInt | None = None
    stampDuty: StrictFloat | StrictInt | None = None
    benchmarkFees: StrictFloat | StrictInt | None = None
    slippageCost: StrictFloat | StrictInt | None = None
    benchmarkSlippageCost: StrictFloat | StrictInt | None = None
    finalEquity: StrictFloat | StrictInt | None = None
    benchmarkFinalEquity: StrictFloat | StrictInt | None = None


class FinancialBacktestEvaluationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    startDate: str
    endDate: str
    baselineDate: str | None
    startingEquity: StrictFloat | StrictInt
    startingBenchmarkEquity: StrictFloat | StrictInt
    tradingDays: StrictInt
    metrics: FinancialBacktestComparisonMetrics


class FinancialBacktestEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outOfSampleStartDate: str
    inSample: FinancialBacktestEvaluationWindow
    outOfSample: FinancialBacktestEvaluationWindow
    notice: str


class FinancialBacktestComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runId: str
    status: str
    modelId: str | None
    modelConfigHash: str | None
    strategy: str | None
    strategyHash: str | None
    callsUsed: int | None
    tokensUsed: int | None
    maxTokens: int | None
    metrics: FinancialBacktestComparisonMetrics | None
    evaluation: FinancialBacktestEvaluation | None
    parameterValue: float | None = None


class FinancialBacktestComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    comparisonId: str
    axis: Literal["strategy", "model", "parameter"]
    status: Literal["comparable", "incomplete", "incompatible"]
    reasons: list[FinancialBacktestComparisonReason]
    dataHash: str | None
    commonParamsHash: str | None
    outOfSampleStartDate: str | None
    rows: list[FinancialBacktestComparisonRow]
    notice: str
    parameterKey: Literal[
        "maxPositionPct",
        "decisionInterval",
        "commissionBps",
        "minimumCommission",
        "slippageBps",
        "maxParticipationPct",
    ] | None = None


class FinancialBacktestExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agentId: str
    runId: str
    format: Literal["json", "csv"]
    schemaVersion: Literal[1, 2] = 1
    fileName: str
    mediaType: str
    encoding: Literal["utf8", "base64"]
    content: str
