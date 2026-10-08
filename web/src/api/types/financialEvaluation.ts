export type FinancialLesson = { id: string; text: string; createdAt: string; refs: Array<{ type: string; id: string }> };
export type FinancialClaimRequest = {
  clientRequestId: string; sessionId: string; turnId: string; symbol: string;
  dueDate: string; direction: "up" | "down"; thresholdPct: number; claimText: string;
};
export type FinancialClaim = Omit<FinancialClaimRequest, "clientRequestId"> & {
  id: string; agentId: string; analysisDate: string; revision: number;
  status: "pending" | "due" | "verified" | "unverifiable";
  registeredBeforeDue: boolean; retrospective: boolean;
  outcome: "hit" | "miss" | null; checkedAt: string | null;
  evidence: { baseDate: string; baseClose: number; dueDateQuoteDate: string; dueClose: number; returnPct: number; sourceUrl: string; fetchedAt: string; seriesHash: string } | null;
  error: { code: string; unavailableReason: string } | null;
  lesson: FinancialLesson | null;
};
export type FinancialClaimPage = { agentId: string; items: FinancialClaim[]; limit: number };
export type FinancialBacktestRequest = { symbol: string; startDate: string; endDate: string; window: number; commissionBps: number; slippageBps: number };
export type FinancialBacktestResult = {
  symbol: string; startDate: string; endDate: string; window: number;
  metrics: { totalReturnPct: number; benchmarkReturnPct: number; excessReturnPct: number; maxDrawdownPct: number; tradeCount: number; fees: number };
  equity: Array<{ date: string; equity: number; benchmarkEquity: number }>;
  trades: Array<{ signalDate: string; date: string; side: "buy" | "sell"; price: number; units: number; fee: number }>;
  source: string; sourceUrl: string; fetchedAt: string; adjustment: string; dataHash: string; notice: string;
};
