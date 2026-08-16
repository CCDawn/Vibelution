import { fetchJson } from "./client";
import type { HealthDiagnostics } from "./types";

export function fetchHealthDiagnostics(): Promise<HealthDiagnostics> {
  return fetchJson<HealthDiagnostics>("/api/diagnostics/health");
}
