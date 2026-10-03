import { fetchJson } from "./client";
import type { HealthDiagnostics } from "./types";

export function fetchHealthDiagnostics(options?: { signal?: AbortSignal }): Promise<HealthDiagnostics> {
  return fetchJson<HealthDiagnostics>("/api/diagnostics/health", { signal: options?.signal });
}
