import { fetchJson } from "./client";
import type { UsageSummaryResponse } from "./types";

export function fetchUsageSummary(): Promise<UsageSummaryResponse> {
  return fetchJson<UsageSummaryResponse>("/api/usage/summary");
}

/** Session and Agent identity are explicit; the global usage view is never a fallback. */
export async function fetchSessionUsageSummary(sessionId: string, agentId: string): Promise<UsageSummaryResponse> {
  if (!sessionId || !agentId) throw new Error("SESSION_USAGE_IDENTITY_REQUIRED");
  const query = new URLSearchParams({ scope: "session_agent", sessionId, agentId });
  const result = await fetchJson<UsageSummaryResponse>(`/api/usage/summary?${query}`);
  if (result.scope !== "session_agent" || result.filters?.sessionId !== sessionId || result.filters?.agentId !== agentId)
    throw new Error("SESSION_USAGE_IDENTITY_MISMATCH");
  return result;
}
