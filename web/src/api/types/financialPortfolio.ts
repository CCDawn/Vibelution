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
