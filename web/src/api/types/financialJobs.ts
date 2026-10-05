import type { FinancialTeamRunCreateRequest } from "./financialTeam";

export type FinancialJobExecutionKind = "now" | "once" | "daily" | "weekdays";
export type FinancialJobDepth = FinancialTeamRunCreateRequest["depth"];
export type FinancialJobPeriod = FinancialTeamRunCreateRequest["periodDays"];

export type FinancialJobExecutionRequest = {
  kind: FinancialJobExecutionKind;
  scheduledAt?: string;
  timeOfDay?: string;
  timezone: "Asia/Shanghai";
};

export type FinancialResearchScheduleCreateRequest = {
  symbols: string[];
  periodDays: FinancialJobPeriod;
  depth: FinancialJobDepth;
  execution: FinancialJobExecutionRequest;
  researchDate?: string;
};

export type FinancialResearchSchedule = {
  scheduleId: string;
  assistantAgentId: string;
  symbols: string[];
  periodDays: FinancialJobPeriod;
  depth: FinancialJobDepth;
  execution: {
    kind: FinancialJobExecutionKind;
    scheduledAt: string | null;
    timeOfDay: string | null;
    timezone: "Asia/Shanghai";
  };
  researchDate: string | null;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
  nextRunAt: string | null;
  lastBatchId: string | null;
  lastTriggeredAt: string | null;
};

export type FinancialResearchBatchStatus = "queued" | "running" | "stop_requested" | "completed" | "partial" | "failed" | "stopped" | "blocked";
export type FinancialResearchBatchItemStatus = "queued" | "preparing" | "submitting" | "running" | "completed" | "failed" | "cancelled" | "blocked" | "skipped";

export type FinancialResearchBatchTurnRef = {
  role: "market" | "fundamental" | "news" | "bull" | "bear" | "synthesis";
  sessionId: string;
  turnId: string;
};

export type FinancialResearchBatchItem = {
  symbol: string;
  status: FinancialResearchBatchItemStatus;
  runId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  terminalReason: string | null;
  turnRefs: FinancialResearchBatchTurnRef[];
};

export type FinancialResearchBatch = {
  batchId: string;
  scheduleId: string | null;
  assistantAgentId: string;
  status: FinancialResearchBatchStatus;
  triggeredAt: string;
  updatedAt: string;
  researchDate: string;
  periodDays: FinancialJobPeriod;
  depth: FinancialJobDepth;
  symbols: string[];
  terminalReason: string | null;
  items: FinancialResearchBatchItem[];
};

export type FinancialResearchScheduleList = { assistantAgentId: string; schedules: FinancialResearchSchedule[] };
export type FinancialResearchBatchList = { assistantAgentId: string; batches: FinancialResearchBatch[] };
export type FinancialResearchScheduleCreateResponse = { schedule: FinancialResearchSchedule; batch: FinancialResearchBatch | null };
