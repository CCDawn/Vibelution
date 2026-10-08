export type AIBacktestRequest = {
  symbol: string; startDate: string; endDate: string; strategy: string;
  initialCash: number; maxPositionPct: number; decisionInterval: number;
  commissionBps: number; minimumCommission: number;
  slippageBps: number; maxDecisions: number; maxTokens: number; modelId?: string;
};
export type AIBacktestPreview = {
  agentId: string; previewId: string; expiresAt: string; symbol: string; modelId: string;
  dateCoverage: { requestedStartDate: string; requestedEndDate: string; actualStartDate: string | null; actualEndDate: string | null; availableStartDate: string | null; availableEndDate: string | null; tradingDays: number; warmupBars: number; providerWindows: Array<{ startDate: string; endDate: string; rawBars: number; qfqBars: number; calendarBars: number }>; complete: boolean; tradingCalendarStatus?: string };
  decisionCount: number; maxDecisions: number; maxTokens: number;
  paramsHash: string; dataHash: string; modelConfigHash?: string; actionsStatus: string;
  warnings: string[]; canStart: boolean; blockReason: string | null;
  params?: AIBacktestRequest; source?: string; sourceUrl?: string; notice?: string;
};
export type AIBacktestDecision = {
  date: string; targetWeight: number; reason: string; confidence?: number;
  inputHash: string; decisionHash: string; modelId: string; attempts: number; tokens: number;
};
export type AIBacktestRun = {
  runId: string; agentId: string; symbol: string;
  status: "queued" | "running" | "stop_requested" | "stopped" | "blocked" | "paused_unknown" | "failed" | "completed";
  progress: number; currentDecisionDate: string | null;
  decisionCount: number; completedDecisionCount: number; callsUsed: number; tokensUsed: number; maxTokens: number;
  modelId: string; paramsHash: string; dataHash: string; modelConfigHash?: string;
  decisions: AIBacktestDecision[];
  metrics: { totalReturnPct: number; benchmarkReturnPct: number; excessReturnPct: number; maxDrawdownPct: number; tradeCount: number; fees: number; annualizedReturnPct?: number | null; sharpeRatio?: number | null; winRatePct?: number | null } | null;
  equity: Array<{ date: string; equity: number; benchmarkEquity: number; cash?: number; units?: number }>;
  trades: Array<{ signalDate: string; date: string; side: "buy" | "sell"; price: number; units: number; fee: number }>;
  orders: Array<{ signalDate?: string; date: string; side?: string; status: string; reason?: string }>;
  benchmarkOrders?: AIBacktestRun["orders"];
  startedAt: string | null; updatedAt: string; completedAt: string | null; terminalReason: string | null;
  warnings?: string[]; notice?: string; uncertainDecisionDate?: string | null; tokenAccounting?: "measured" | "estimated" | "reserved";
  params?: AIBacktestRequest; source?: string; sourceUrl?: string;
};
export type AIBacktestSummary = Pick<AIBacktestRun, "agentId" | "runId" | "symbol" | "status" | "decisionCount" | "completedDecisionCount" | "progress" | "modelId" | "paramsHash" | "dataHash" | "startedAt" | "updatedAt" | "completedAt" | "terminalReason">;
export type AIBacktestPage = { items: AIBacktestSummary[]; nextCursor: string | null };
export type AIBacktestExport = { fileName: string; mediaType: string; encoding: "utf8" | "base64"; content: string };
