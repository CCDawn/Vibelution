import { fetchJson } from "./client";
import type { FinancialBacktestRequest, FinancialBacktestResult, FinancialClaim, FinancialClaimPage, FinancialClaimRequest, FinancialLesson } from "./types/financialEvaluation";

export const financialEvaluationKeys = {
  claims: (agentId: string) => ["finance", "validation", agentId] as const,
  lessons: (agentId: string, symbol: string, date: string) => ["finance", "reflection-context", agentId, symbol, date] as const,
};
const base = (agentId: string) => `/api/financial-reports/${encodeURIComponent(agentId)}`;
const claimPath = (agentId: string, id: string) => `${base(agentId)}/validations/${encodeURIComponent(id)}`;
const post = <T>(url: string, payload?: unknown, signal?: AbortSignal) => fetchJson<T>(url, { method: "POST", signal, headers: { "Content-Type": "application/json" }, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}) });
export const fetchFinancialClaims = (agentId: string, signal?: AbortSignal) => fetchJson<FinancialClaimPage>(`${base(agentId)}/validations`, { signal });
export const createFinancialClaim = (agentId: string, payload: FinancialClaimRequest) => post<FinancialClaim>(`${base(agentId)}/validations`, payload);
export const checkFinancialClaim = (agentId: string, id: string) => post<FinancialClaim>(`${claimPath(agentId, id)}/check`);
export const fetchFinancialFeedback = (agentId: string, id: string) => fetchJson<{ id: string; text: string }>(`${claimPath(agentId, id)}/feedback`);
export const saveFinancialLesson = (agentId: string, id: string, text: string, clientRequestId: string) => post<FinancialLesson>(`${claimPath(agentId, id)}/lesson`, { text, clientRequestId });
export const fetchFinancialReflection = (agentId: string, symbol: string, analysisDate: string, signal?: AbortSignal) => fetchJson<{ items: FinancialLesson[] }>(`${base(agentId)}/reflection-context?${new URLSearchParams({ symbol, analysisDate })}`, { signal });
export const runFinancialBacktest = (agentId: string, payload: FinancialBacktestRequest, signal?: AbortSignal) => post<FinancialBacktestResult>(`${base(agentId)}/backtest`, payload, signal);
