export type FinancialPortfolioReturnSeriesStatus =
  | "available"
  | "unavailable"
  | "deadline"
  | "capacity_skipped"
  | "limit_skipped"
  | "not_valued";

export type FinancialPortfolioPosition = {
  symbol: string;
  ticker: string;
  name: string;
  market: string;
  quantity: number;
  markPriceYuan: string | null;
  marketValueYuan: string | null;
  unrealizedPnlYuan: string | null;
  weightPercent: string | null;
  valuationStatus: "fresh" | "stale" | "unavailable";
  quoteTimestamp: string;
  quoteFetchedAt: string;
  source: string;
  sourceUrl: string;
  returnSeriesStatus: FinancialPortfolioReturnSeriesStatus;
};

export type FinancialPortfolioCorrelation = {
  firstSymbol: string;
  firstName: string;
  secondSymbol: string;
  secondName: string;
  correlation: number;
  observations: number;
  startDate: string;
  endDate: string;
};

export type FinancialPortfolioResearch = {
  agentId: string;
  accountId: string;
  generatedAt: string;
  source: string;
  sourceUrl: string;
  adjustment: "qfq";
  period: "day";
  simulationOnly: true;
  summary: {
    equityYuan: string | null;
    cashYuan: string | null;
    marketValueYuan: string | null;
    cashWeightPercent: string | null;
    positionCount: number;
    valuedPositionCount: number;
    valuationComplete: boolean;
    maxPositionWeightPercent: string | null;
    topThreeWeightPercent: string | null;
    correlationPairCount: number;
    highCorrelationPairCount: number;
    insufficientCorrelationPairCount: number;
    unavailableCorrelationPairCount: number;
  };
  positions: FinancialPortfolioPosition[];
  correlations: FinancialPortfolioCorrelation[];
  coverage: {
    eligiblePositionCount: number;
    selectedPositionCount: number;
    candleLoadedPositionCount: number;
    candleUnavailablePositionCount: number;
    budgetSkippedPositionCount: number;
    capacitySkippedPositionCount: number;
    deadlineSkippedPositionCount: number;
    unvaluedPositionCount: number;
    maxAnalyzedPositions: number;
    maxConcurrentFetches: number;
    deadlineSeconds: number;
    minimumCorrelationObservations: number;
    analyzedSymbols: string[];
    budgetSkippedSymbols: string[];
    unavailableSymbols: string[];
  };
  notice: string;
};

export type FinancialPortfolioProposalStatus = "generating" | "ready" | "blocked" | "failed" | "executed";

export type FinancialPortfolioRebalancePolicy = {
  maxPositionPct: number;
  minCashPct: number;
  maxTurnoverPct: number;
  maxQuoteAgeHours: number;
};

export type FinancialPortfolioRebalanceTarget = {
  symbol: string;
  weightPct: number;
  reason: string;
};

export type FinancialPortfolioProposal = {
  proposalId: string;
  agentId: string;
  status: FinancialPortfolioProposalStatus;
  createdAt: string;
  expiresAt: string;
  modelId: string;
  reportRefs: Array<{ sessionId: string; turnId: string; contentHash: string }>;
  targets: FinancialPortfolioRebalanceTarget[];
  summaryReason: string;
  riskChecks: Array<{ code: string; label: string; passed: boolean; detail: string }>;
  orders: Array<{
    symbol: string;
    name: string;
    side: "buy" | "sell";
    quantity: number;
    priceYuan: string;
    grossAmountYuan: string;
    feeYuan: string;
    reason?: string;
  }>;
  metrics: {
    equityYuan: string;
    cashAfterYuan: string;
    turnoverPct: string;
    feesYuan: string;
  };
  policy: FinancialPortfolioRebalancePolicy;
  planHash: string;
  error: string | null;
  execution: { batchId: string; executedAt: string } | null;
};

export type FinancialPortfolioProposalList = { items: FinancialPortfolioProposal[] };

export type FinancialPortfolioProposalCreateRequest = {
  clientRequestId: string;
  symbols: string[];
  reports: Array<{ sessionId: string; turnId: string }>;
  instruction: string;
  policy: FinancialPortfolioRebalancePolicy;
};

export type FinancialPortfolioProposalPreviewRequest = {
  targets: FinancialPortfolioRebalanceTarget[];
  policy: FinancialPortfolioRebalancePolicy;
};

export type FinancialPortfolioProposalApprovalRequest = {
  planHash: string;
  confirmSimulation: true;
};
