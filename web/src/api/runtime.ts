import { fetchJson } from "./client";
import type { RuntimeSummary } from "./types";

export function fetchRuntimeSummary(): Promise<RuntimeSummary> {
  return fetchJson<RuntimeSummary>("/api/runtime/summary");
}
