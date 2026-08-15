import { fetchJson } from "./client";

export function fetchSourceCollectionSummary<T = Record<string, unknown>>(
  teamId: string,
  options?: { signal?: AbortSignal; runId?: string },
): Promise<T> {
  const search = new URLSearchParams();
  if (options?.runId) {
    search.set("runId", options.runId);
  }
  const suffix = search.toString();
  const path = `/api/teams/${encodeURIComponent(teamId)}/workflow-orchestration/source-collection/summary`;
  return fetchJson<T>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}
