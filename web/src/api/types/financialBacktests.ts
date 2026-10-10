export type AIBacktestParams = {
  strategy: string;
  initialCash: number;
  maxPositionPct: number;
  maxParticipationPct?: number | null;
  quantityRuleVersion?: "ashare_quantity_v2" | "legacy_100_v1" | null;
  corporateActionPolicy?: "block" | "verified_cash_dividends" | null;
  decisionInterval: number;
  commissionBps: number;
  minimumCommission: number;
  slippageBps: number;
  maxDecisions: number;
  maxTokens: number;
  outOfSampleStartDate?: string;
};

type AIBacktestRequestBase = AIBacktestParams & {
  startDate: string;
  endDate: string;
  modelId?: string;
  dataSource?: "tencent" | "eastmoney" | "sina" | "auto";
  researchInput?: "price_only" | "announcements" | "financial_reports";
};

export type AIBacktestRequest = AIBacktestRequestBase &
  (
    | { symbol: string; symbols?: never }
    | { symbol?: never; symbols: string[] }
  );

export type AIBacktestDateCoverage = {
  requestedStartDate: string;
  requestedEndDate: string;
  actualStartDate: string | null;
  actualEndDate: string | null;
  availableStartDate: string | null;
  availableEndDate: string | null;
  tradingDays: number;
  warmupBars: number;
  providerWindows: Array<{
    startDate: string;
    endDate: string;
    rawBars: number;
    qfqBars: number;
    calendarBars: number;
  }>;
  complete: boolean;
  tradingCalendarStatus?: string;
};

export type AIBacktestMetrics = {
  totalReturnPct: number;
  benchmarkReturnPct: number;
  excessReturnPct: number;
  maxDrawdownPct: number;
  tradeCount: number;
  fees: number;
  annualizedReturnPct?: number | null;
  sharpeRatio?: number | null;
  winRatePct?: number | null;
  grossDividends?: number;
  dividendTaxPaid?: number;
  dividendTaxPayable?: number;
  netDividendIncome?: number;
  benchmarkGrossDividends?: number;
  benchmarkDividendTaxPaid?: number;
  benchmarkDividendTaxPayable?: number;
  benchmarkNetDividendIncome?: number;
};

export type AIBacktestEvaluationWindow = {
  startDate: string;
  endDate: string;
  baselineDate: string | null;
  startingEquity: number;
  startingBenchmarkEquity: number;
  tradingDays: number;
  metrics: AIBacktestMetrics;
};

export type AIBacktestEvaluation = {
  outOfSampleStartDate: string;
  inSample: AIBacktestEvaluationWindow;
  outOfSample: AIBacktestEvaluationWindow;
  notice: string;
};

export type AIBacktestRobustnessWindow = {
  label: string;
  startDate: string;
  endDate: string;
  baselineDate: string | null;
  tradingDays: number;
  complete: boolean | null;
  metrics: Pick<AIBacktestMetrics, "totalReturnPct" | "benchmarkReturnPct" | "excessReturnPct" | "maxDrawdownPct" | "fees" | "tradeCount">;
};

export type AIBacktestRobustness = {
  schemaVersion: 1;
  status: "available" | "insufficient_sample" | "unavailable";
  scope: "out_of_sample" | "full_period";
  windowSize: 63;
  minCompleteWindows: 4;
  completeWindowCount: number;
  partialWindowCount: number;
  outperformingWindowRatePct: number | null;
  evaluatedStartDate: string | null;
  evaluatedEndDate: string | null;
  tradingDays: number;
  annualWindows: AIBacktestRobustnessWindow[];
  fixedWindows: AIBacktestRobustnessWindow[];
  error: string | null;
  notice: string;
};

export type AIBacktestAdvancedMetrics = Partial<Pick<AIBacktestMetrics,
  "totalReturnPct" | "benchmarkReturnPct" | "excessReturnPct" | "maxDrawdownPct" | "tradeCount" | "fees"
>> & {
  commissionFees?: number | null;
  stampDuty?: number | null;
  slippageCost?: number | null;
  benchmarkFees?: number | null;
  benchmarkSlippageCost?: number | null;
  grossTurnover?: number | null;
};

export type AIBacktestCostScenario = {
  id: "baseline" | "cost_1_5x" | "cost_2x";
  status: "available" | "unavailable";
  costMultiplier: number;
  commissionBps: number;
  minimumCommission: number;
  slippageBps: number;
  metrics: AIBacktestAdvancedMetrics | null;
  outOfSampleMetrics: AIBacktestAdvancedMetrics | null;
  error: string | null;
};

export type AIBacktestCostStress = {
  status: "available" | "partial" | "unavailable";
  scenarios: AIBacktestCostScenario[];
  error?: string | null;
  notice: string;
};

export type AIBacktestReturnUncertainty = {
  status: "available" | "insufficient_sample" | "unavailable";
  method: "newey_west_hac";
  metric: "annualized_log_excess_return_pct";
  confidenceLevel: number;
  observations: number;
  lag: number | null;
  pointEstimatePct: number | null;
  lowerPct: number | null;
  upperPct: number | null;
  error: string | null;
  notice: string;
};

export type AIBacktestAdvancedEvaluation = {
  schemaVersion: 1;
  basis: "frozen_decisions";
  status: "available" | "unavailable";
  outOfSampleStartDate: string | null;
  costStress: AIBacktestCostStress;
  returnUncertainty: AIBacktestReturnUncertainty;
  error?: string | null;
  notice: string;
};

export type AIBacktestBenchmarkStatus = "invested" | "partial_cash_sleeves" | "cash_only";

export type AIBacktestComparisonProvenance = {
  contractVersion: string;
  commonParamsHash: string;
  strategyHash: string;
  sourceRunId?: string;
};

export type AIBacktestParameterKey =
  | "maxPositionPct"
  | "decisionInterval"
  | "commissionBps"
  | "minimumCommission"
  | "slippageBps"
  | "maxParticipationPct";
export type AIBacktestForkPreviewRequest = {
  strategy?: string;
  modelId?: string;
  maxTokens?: number;
  maxPositionPct?: number;
  decisionInterval?: number;
  commissionBps?: number;
  minimumCommission?: number;
  slippageBps?: number;
  maxParticipationPct?: number;
};
export type AIBacktestComparisonAxis = "strategy" | "model" | "parameter";
export type AIBacktestComparisonRequest =
  | { runIds: string[]; axis: "strategy" | "model"; parameterKey?: never }
  | { runIds: string[]; axis: "parameter"; parameterKey: AIBacktestParameterKey };
export type AIBacktestComparisonStatus = "comparable" | "incomplete" | "incompatible";
export type AIBacktestComparisonReason = { code: string; runIds: string[]; message: string };

export type AIBacktestComparisonMetrics = {
  totalReturnPct?: number | null;
  benchmarkReturnPct?: number | null;
  excessReturnPct?: number | null;
  annualizedReturnPct?: number | null;
  benchmarkAnnualizedReturnPct?: number | null;
  maxDrawdownPct?: number | null;
  maxDrawdownSessions?: number | null;
  volatilityAnnualizedPct?: number | null;
  sharpeRatio?: number | null;
  benchmarkMaxDrawdownPct?: number | null;
  tradeCount?: number | null;
  closedTradeCount?: number | null;
  winningTradeCount?: number | null;
  winRatePct?: number | null;
  grossTurnover?: number | null;
  fees?: number | null;
  commissionFees?: number | null;
  stampDuty?: number | null;
  benchmarkFees?: number | null;
  slippageCost?: number | null;
  benchmarkSlippageCost?: number | null;
  finalEquity?: number | null;
  benchmarkFinalEquity?: number | null;
};

export type AIBacktestComparisonEvaluationWindow = Omit<AIBacktestEvaluationWindow, "metrics"> & {
  metrics: AIBacktestComparisonMetrics;
};

export type AIBacktestComparisonEvaluation = Omit<AIBacktestEvaluation, "inSample" | "outOfSample"> & {
  inSample: AIBacktestComparisonEvaluationWindow;
  outOfSample: AIBacktestComparisonEvaluationWindow;
};

export type AIBacktestComparisonRow = {
  runId: string;
  status: string;
  modelId: string | null;
  modelConfigHash: string | null;
  strategy: string | null;
  strategyHash: string | null;
  callsUsed: number | null;
  tokensUsed: number | null;
  maxTokens: number | null;
  metrics: AIBacktestComparisonMetrics | null;
  evaluation: AIBacktestComparisonEvaluation | null;
  parameterValue?: number | null;
};

export type AIBacktestComparisonResult = {
  comparisonId: string;
  axis: AIBacktestComparisonAxis;
  status: AIBacktestComparisonStatus;
  reasons: AIBacktestComparisonReason[];
  dataHash: string | null;
  commonParamsHash: string | null;
  outOfSampleStartDate: string | null;
  rows: AIBacktestComparisonRow[];
  notice: string;
  parameterKey?: AIBacktestParameterKey | null;
};

type AIBacktestDecisionBase = {
  date: string;
  reason: string;
  confidence?: number;
  inputHash: string;
  decisionHash: string;
  modelId: string;
  attempts: number;
  tokens: number;
};

export type AIBacktestDecision = AIBacktestDecisionBase &
  (
    | { targetWeight: number; targetWeights?: never }
    | { targetWeight?: never; targetWeights: Record<string, number> }
  );

export type AIBacktestOrder = {
  signalDate?: string;
  date: string;
  symbol?: string;
  side?: string;
  status: string;
  reason?: string;
  filledShares?: number;
  price?: number;
  notional?: number;
  fee?: number;
};

export type AIBacktestTrade = {
  signalDate: string;
  date: string;
  symbol?: string;
  side: "buy" | "sell";
  price: number;
  units: number;
  fee: number;
};

export type AIBacktestResearchCoverage = {
  status: "available" | "partial";
  groupCount: number;
  availableGroupCount: number;
  partialGroupCount: number;
  failedGroupCount: number;
  itemCount: number;
  notice: string;
  warnings: string[];
};

export type AIBacktestActionCoverage = {
  status: "complete";
  ruleVersion: "ashare_cash_dividend_v1";
  artifactHash: string;
  startDate: string;
  endDate: string;
  eventCount: number;
};

export type AIBacktestDividendAudit = {
  schemaVersion: 1;
  ruleVersion: "ashare_cash_dividend_v1";
  artifactHash: string;
  symbol: string;
  settlementRounding: "unverified_decimal_exact";
  receivable: string;
  taxPayable: string;
  taxTotal: string;
  dividendsTotal: string;
  events: Array<{
    actionId: string; noticeId: string; publishedDate: string; title: string; sourceUrl: string; pdfSha256: string;
    recordDate: string; exDate: string; paymentDate: string; cashPerShare: string;
    recordCaptured: boolean; ledgerApplied: boolean; entitledShares: number; grossAmount: string; exRecognized: boolean;
    paymentComplete: boolean; taxPayable: string; taxTotal: string; taxPaid: string;
  }>;
  lots: Array<{ acquiredDate: string; shares: number; dividendRights: Record<string, number> }>;
};

export type AIBacktestPreview = {
  agentId: string;
  previewId: string;
  expiresAt: string;
  symbol: string | null;
  symbols?: string[];
  modelId: string;
  dateCoverage: AIBacktestDateCoverage;
  assetCoverage?: Record<string, AIBacktestDateCoverage>;
  assetDataHashes?: Record<string, string>;
  assetSources?: Record<string, {
    source?: string;
    sourceUrl?: string;
    fetchedAt?: string;
  }>;
  outOfSampleStartDate?: string | null;
  decisionCount: number;
  maxDecisions: number;
  maxTokens: number;
  estimatedTokens?: number;
  paramsHash: string;
  dataHash: string;
  researchInput?: "price_only" | "announcements" | "financial_reports";
  researchHash?: string | null;
  researchCoverage?: AIBacktestResearchCoverage | null;
  modelConfigHash?: string;
  actionsStatus: string;
  corporateActionCoverage?: Record<string, AIBacktestActionCoverage> | null;
  warnings: string[];
  canStart: boolean;
  blockReason: string | null;
  params?: AIBacktestParams;
  source?: string;
  sourceUrl?: string;
  notice?: string;
  comparisonProvenance?: AIBacktestComparisonProvenance | null;
};

export type AIBacktestRun = {
  runId: string;
  agentId: string;
  symbol: string | null;
  symbols?: string[];
  status:
    | "queued"
    | "running"
    | "stop_requested"
    | "stopped"
    | "blocked"
    | "paused_unknown"
    | "failed"
    | "completed";
  progress: number;
  currentDecisionDate: string | null;
  decisionCount: number;
  completedDecisionCount: number;
  callsUsed: number;
  tokensUsed: number;
  maxTokens: number;
  modelId: string;
  paramsHash: string;
  dataHash: string;
  researchInput?: "price_only" | "announcements" | "financial_reports";
  researchHash?: string | null;
  researchCoverage?: AIBacktestResearchCoverage | null;
  modelConfigHash?: string;
  params?: AIBacktestParams;
  outOfSampleStartDate?: string | null;
  dateCoverage?: AIBacktestDateCoverage;
  assetCoverage?: Record<string, AIBacktestDateCoverage>;
  assetDataHashes?: Record<string, string>;
  assetSources?: Record<string, {
    source?: string;
    sourceUrl?: string;
    fetchedAt?: string;
  }>;
  decisions: AIBacktestDecision[];
  metrics: AIBacktestMetrics | null;
  corporateActionCoverage?: Record<string, AIBacktestActionCoverage> | null;
  dividendAccounting?: AIBacktestDividendAudit | Record<string, AIBacktestDividendAudit> | null;
  benchmarkDividendAccounting?: AIBacktestDividendAudit | Record<string, AIBacktestDividendAudit> | null;
  evaluation?: AIBacktestEvaluation | null;
  robustness?: AIBacktestRobustness | null;
  advancedEvaluation?: AIBacktestAdvancedEvaluation | null;
  equity: Array<{
    date: string;
    equity: number;
    benchmarkEquity: number;
    cash?: number;
    units?: number;
    positions?: Record<string, number>;
    dividendReceivable?: number;
    dividendTaxPayable?: number;
    benchmarkDividendReceivable?: number;
    benchmarkDividendTaxPayable?: number;
  }>;
  trades: AIBacktestTrade[];
  orders: AIBacktestOrder[];
  benchmarkOrders?: AIBacktestOrder[];
  benchmarkStatus?: AIBacktestBenchmarkStatus;
  unfilledBenchmarkSymbols?: string[];
  comparisonProvenance?: AIBacktestComparisonProvenance | null;
  startedAt: string | null;
  updatedAt: string;
  completedAt: string | null;
  terminalReason: string | null;
  executionFailure?: {
    failure: "insufficient_cash_for_dividend_tax";
    date: string;
    symbol: string;
    availableCash: string;
    dividendTaxDue: string;
    projectedCashAfterTax: string;
    order: AIBacktestOrder;
    trade: AIBacktestTrade;
  } | null;
  warnings?: string[];
  notice?: string;
  uncertainDecisionDate?: string | null;
  tokenAccounting?: "measured" | "estimated" | "reserved";
  source?: string;
  sourceUrl?: string;
};

export type AIBacktestSummary = {
  runId: string;
  agentId: string;
  symbol: string | null;
  symbols?: string[];
  status: AIBacktestRun["status"];
  decisionCount: number;
  completedDecisionCount: number;
  progress: number;
  modelId: string;
  paramsHash: string;
  dataHash: string;
  startedAt: string | null;
  updatedAt: string;
  completedAt: string | null;
  terminalReason: string | null;
  totalReturnPct?: number | null;
  maxDrawdownPct?: number | null;
  outOfSampleStartDate?: string | null;
  evaluation?: AIBacktestEvaluation | null;
};

export type AIBacktestPage = { items: AIBacktestSummary[]; nextCursor: string | null };
export type AIBacktestExport = {
  schemaVersion: 1 | 2;
  fileName: string;
  mediaType: string;
  encoding: "utf8" | "base64";
  content: string;
};
