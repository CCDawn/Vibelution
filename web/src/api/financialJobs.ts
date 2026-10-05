import { fetchJson } from "./client";
import type {
  FinancialResearchBatch,
  FinancialResearchBatchList,
  FinancialResearchSchedule,
  FinancialResearchScheduleCreateRequest,
  FinancialResearchScheduleCreateResponse,
  FinancialResearchScheduleList,
} from "./types/financialJobs";

export type * from "./types/financialJobs";

function rootPath(assistantAgentId: string): string {
  return `/api/financial-jobs/${encodeURIComponent(assistantAgentId)}`;
}

export function fetchFinancialResearchSchedules(assistantAgentId: string, options?: { signal?: AbortSignal }): Promise<FinancialResearchScheduleList> {
  return fetchJson<FinancialResearchScheduleList>(`${rootPath(assistantAgentId)}/schedules`, { signal: options?.signal });
}

export function createFinancialResearchSchedule(assistantAgentId: string, request: FinancialResearchScheduleCreateRequest, idempotencyKey: string): Promise<FinancialResearchScheduleCreateResponse> {
  return fetchJson<FinancialResearchScheduleCreateResponse>(`${rootPath(assistantAgentId)}/schedules`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(request),
  });
}

export function updateFinancialResearchSchedule(assistantAgentId: string, scheduleId: string, enabled: boolean): Promise<FinancialResearchSchedule> {
  return fetchJson<FinancialResearchSchedule>(`${rootPath(assistantAgentId)}/schedules/${encodeURIComponent(scheduleId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}

export function fetchFinancialResearchBatches(assistantAgentId: string, options?: { signal?: AbortSignal }): Promise<FinancialResearchBatchList> {
  return fetchJson<FinancialResearchBatchList>(`${rootPath(assistantAgentId)}/batches`, { signal: options?.signal });
}

export function fetchFinancialResearchBatch(assistantAgentId: string, batchId: string, options?: { signal?: AbortSignal }): Promise<FinancialResearchBatch> {
  return fetchJson<FinancialResearchBatch>(`${rootPath(assistantAgentId)}/batches/${encodeURIComponent(batchId)}`, { signal: options?.signal });
}

export function stopFinancialResearchBatch(assistantAgentId: string, batchId: string): Promise<FinancialResearchBatch> {
  return fetchJson<FinancialResearchBatch>(`${rootPath(assistantAgentId)}/batches/${encodeURIComponent(batchId)}/stop`, { method: "POST" });
}

export function retryFinancialResearchBatch(assistantAgentId: string, batchId: string): Promise<FinancialResearchBatch> {
  return fetchJson<FinancialResearchBatch>(`${rootPath(assistantAgentId)}/batches/${encodeURIComponent(batchId)}/retry`, { method: "POST" });
}
