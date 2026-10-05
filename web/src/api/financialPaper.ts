import { FetchJsonHttpError, fetchJson } from "./client";
import type { PaperAccountSnapshot, PaperOrderRequest, PaperReviewSnapshot } from "./types/financialPaper";
export type {
  PaperAccountSnapshot,
  PaperFeePolicy,
  PaperOrder,
  PaperOrderRequest,
  PaperPosition,
  PaperReviewDay,
  PaperReviewSnapshot,
  PaperReviewSummary,
  PaperSide,
} from "./types/financialPaper";

export const financialPaperKeys = {
  account: (agentId: string) => ["financial-paper", agentId, "account"] as const,
  review: (agentId: string, month: string) => ["financial-paper", agentId, "review", month] as const,
};

/** Keep transport details inside this domain API; routes only need the domain state. */
export function isFinancialPaperAccountNotOpened(error: unknown): boolean {
  if (!(error instanceof FetchJsonHttpError) || error.status !== 404) return false;
  return /尚未开设模拟账户|模拟账户尚未开设|paper account (?:is )?not open(?:ed)?/i.test(error.message);
}

function agentPath(agentId: string) {
  return `/api/financial-paper/${encodeURIComponent(agentId)}`;
}

export function fetchFinancialPaperAccount(
  agentId: string,
  options?: { signal?: AbortSignal; orderLimit?: number },
): Promise<PaperAccountSnapshot> {
  const query = new URLSearchParams({ orderLimit: String(options?.orderLimit ?? 50) });
  return fetchJson<PaperAccountSnapshot>(`${agentPath(agentId)}?${query.toString()}`, { signal: options?.signal });
}

export function openFinancialPaperAccount(agentId: string): Promise<PaperAccountSnapshot> {
  return fetchJson<PaperAccountSnapshot>(`${agentPath(agentId)}/account`, { method: "POST" });
}

export function submitFinancialPaperOrder(agentId: string, request: PaperOrderRequest): Promise<PaperAccountSnapshot> {
  return fetchJson<PaperAccountSnapshot>(`${agentPath(agentId)}/orders`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function fetchFinancialPaperReview(
  agentId: string,
  month: string,
  options?: { signal?: AbortSignal },
): Promise<PaperReviewSnapshot> {
  const query = new URLSearchParams({ month });
  return fetchJson<PaperReviewSnapshot>(`${agentPath(agentId)}/review?${query.toString()}`, { signal: options?.signal });
}
