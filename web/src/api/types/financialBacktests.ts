export type AIBacktestParams = {
  strategy: string;
  initialCash: number;
  maxPositionPct: number;
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

export type AIBacktestBenchmarkStatus = "invested" | "partial_cash_sleeves" | "cash_only";

export type AIBacktestComparisonProvenance = {
  contractVersion: string;
  commonParamsHash: string;
  strategyHash: string;
  sourceRunId?: string;
};

export type AIBacktestComparisonAxis = "strategy" | "model";
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
  modelConfigHash?: string;
  actionsStatus: string;
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
  evaluation?: AIBacktestEvaluation | null;
  equity: Array<{
    date: string;
    equity: number;
    benchmarkEquity: number;
    cash?: number;
    units?: number;
    positions?: Record<string, number>;
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
