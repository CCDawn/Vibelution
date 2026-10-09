import { fetchJson } from "./client";
import type { AIBacktestComparisonResult, AIBacktestExport, AIBacktestPage, AIBacktestPreview, AIBacktestRequest, AIBacktestRun } from "./types/financialBacktests";

export const financialBacktestKeys = {
  list: (agentId: string) => ["finance", "ai-backtests", agentId] as const,
  run: (agentId: string, runId: string) => ["finance", "ai-backtest", agentId, runId] as const,
};
const base = (agentId: string) => `/api/financial-backtests/${encodeURIComponent(agentId)}`;
const runPath = (agentId: string, runId: string) => `${base(agentId)}/runs/${encodeURIComponent(runId)}`;
const post = <T>(url: string, payload?: unknown, signal?: AbortSignal) => fetchJson<T>(url, { method: "POST", signal, headers: { "Content-Type": "application/json" }, ...(payload !== undefined ? { body: JSON.stringify(payload) } : {}) });
export const previewAIBacktest = (agentId: string, payload: AIBacktestRequest, signal?: AbortSignal) => post<AIBacktestPreview>(`${base(agentId)}/preview`, payload, signal);
export const previewForkAIBacktest = (agentId: string, runId: string, payload: { strategy?: string; modelId?: string; maxTokens?: number }, signal?: AbortSignal) => post<AIBacktestPreview>(`${runPath(agentId, runId)}/fork-preview`, payload, signal);
export const startAIBacktest = (agentId: string, previewId: string, clientRequestId: string) => post<AIBacktestRun>(`${base(agentId)}/runs`, { previewId, clientRequestId });
export const fetchAIBacktests = (agentId: string, cursor?: string, signal?: AbortSignal) => fetchJson<AIBacktestPage>(`${base(agentId)}/runs?${new URLSearchParams({ limit: "20", ...(cursor ? { cursor } : {}) })}`, { signal });
export const fetchAIBacktest = (agentId: string, runId: string, signal?: AbortSignal) => fetchJson<AIBacktestRun>(runPath(agentId, runId), { signal });
export const compareAIBacktests = (agentId: string, payload: { runIds: string[]; axis: "strategy" | "model" }, signal?: AbortSignal) => post<AIBacktestComparisonResult>(`${base(agentId)}/runs/compare`, payload, signal);
export const stopAIBacktest = (agentId: string, runId: string) => post<AIBacktestRun>(`${runPath(agentId, runId)}/stop`);
export const resumeAIBacktest = (agentId: string, runId: string, retry?: { retryUnknownDecisionDate: string; confirmPossibleDuplicateCharge: boolean }) => post<AIBacktestRun>(`${runPath(agentId, runId)}/resume`, retry ?? {});
export async function downloadAIBacktest(agentId: string, runId: string, format: "json" | "csv") {
  const data = await post<AIBacktestExport>(`${runPath(agentId, runId)}/export`, { format });
  if (!data.content || data.content.length > 12_000_000 || !["utf8", "base64"].includes(data.encoding)) throw new Error("回测导出内容无效或超过上限");
  const content = data.encoding === "base64" ? Uint8Array.from(atob(data.content), char => char.charCodeAt(0)) : data.content;
  const url = URL.createObjectURL(new Blob([content], { type: data.mediaType }));
  const link = document.createElement("a"); link.href = url; link.download = data.fileName.replace(/[\\/]/g, "_");
  document.body.append(link);
  try { link.click(); } finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}

export function downloadAIBacktestComparison(result: AIBacktestComparisonResult) {
  const content = JSON.stringify(result, null, 2);
  if (content.length > 4_000_000) throw new Error("比较JSON超过安全导出上限");
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const comparisonId = result.comparisonId.replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80) || "result";
  const link = document.createElement("a"); link.href = url; link.download = `financial-backtest-comparison-${comparisonId}.json`;
  document.body.append(link);
  try { link.click(); } finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
