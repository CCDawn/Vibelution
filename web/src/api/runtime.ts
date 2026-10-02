import { fetchJson } from "./client";
import type { RuntimeSummary } from "./types";

export function fetchRuntimeSummary(init?: { signal?: AbortSignal }): Promise<RuntimeSummary> {
  return fetchJson<RuntimeSummary>("/api/runtime/summary", { signal: init?.signal });
}
