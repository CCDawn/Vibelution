import { fetchJson } from "./client";
import type { ConfigSummary } from "./types";

export function fetchPublicConfig(): Promise<ConfigSummary> {
  return fetchJson<ConfigSummary>("/api/config/public");
}
