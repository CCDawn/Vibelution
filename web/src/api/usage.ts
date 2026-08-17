import { fetchJson } from "./client";
import type { UsageSummaryResponse } from "./types";

export function fetchUsageSummary(): Promise<UsageSummaryResponse> {
  return fetchJson<UsageSummaryResponse>("/api/usage/summary");
}
