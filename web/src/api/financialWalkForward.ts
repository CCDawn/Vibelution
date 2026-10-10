import { fetchJson } from "./client";

export type WalkForwardCandidate = { candidateId: string; maxPositionPct: number };
export type WalkForwardRequest = { trainSessions: number; testSessions: number; stepSessions: number; candidates: WalkForwardCandidate[]; maxTokens: number };
export type WalkForwardWorkflow = WalkForwardRequest & {
  agentId: string; workflowId: string; sourceRunId: string; planHash: string;
  status: "preview" | "queued" | "running" | "stop_requested" | "stopped" | "paused_unknown" | "completed" | "failed" | "blocked";
  estimatedTokens: number; activeRunId: string | null; terminalReason: string | null;
  tokensUsed?: number; budgetTokensCommitted?: number; tokenUsageEstimated?: boolean;
  createdAt: string; updatedAt: string; notice: string;
  folds: Array<{ foldId: string; trainStart: string; trainEnd: string; testStart: string; testEnd: string; selectedCandidateId: string | null; testRunId: string | null; status: string; metrics: { totalReturnPct: number | null; benchmarkReturnPct: number | null; excessReturnPct: number | null; maxDrawdownPct: number | null } | null }>;
};
const base = (agentId: string) => `/api/financial-backtests/${encodeURIComponent(agentId)}`;
const path = (agentId: string, id: string) => `${base(agentId)}/walk-forward/${encodeURIComponent(id)}`;
const post = <T>(url: string, body?: unknown) => fetchJson<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
export const previewWalkForward = (agentId: string, runId: string, body: WalkForwardRequest) => post<WalkForwardWorkflow>(`${base(agentId)}/runs/${encodeURIComponent(runId)}/walk-forward-preview`, body);
export const listWalkForward = (agentId: string, signal?: AbortSignal) => fetchJson<{ items: WalkForwardWorkflow[] }>(`${base(agentId)}/walk-forward`, { signal });
export const getWalkForward = (agentId: string, id: string, signal?: AbortSignal) => fetchJson<WalkForwardWorkflow>(path(agentId, id), { signal });
export const actWalkForward = (agentId: string, id: string, action: "start" | "stop" | "resume") => post<WalkForwardWorkflow>(`${path(agentId, id)}/${action}`);
export async function exportWalkForward(agentId: string, id: string) {
  const data = await post<unknown>(`${path(agentId, id)}/export`);
  const content = JSON.stringify(data, null, 2);
  if (content.length > 12_000_000) throw new Error("滚动验证导出超过大小上限");
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = `walk-forward-${id.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`;
  document.body.append(link);
  try { link.click(); } finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
