import { fetchJson } from "./client";
import type {
  DataProcessingCollectionAssignmentListPayload,
  DataProcessingRunListPayload,
  DataProcessingStatus,
} from "./types";

export function listDataProcessingRuns<T = DataProcessingRunListPayload>(options: {
  limit: number;
  teamId?: string;
  startedFrom?: string;
  profileId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  const search = new URLSearchParams();
  search.set("limit", String(options.limit));
  if (options.teamId) {
    search.set("teamId", options.teamId);
  }
  if (options.startedFrom) {
    search.set("startedFrom", options.startedFrom);
  }
  if (options.profileId) {
    search.set("profileId", options.profileId);
  }
  return fetchJson<T>(`/api/data-processing/runs?${search.toString()}`, {
    signal: options.signal,
  });
}

export function fetchDataProcessingRunStatus<T = DataProcessingStatus>(
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/status`,
    { signal: options?.signal },
  );
}

export function listDataProcessingRunRecords<T>(
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/records`,
    { signal: options?.signal },
  );
}

export function listDataProcessingCollectionAssignments<T = DataProcessingCollectionAssignmentListPayload>(
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/collection-assignments`,
    { signal: options?.signal },
  );
}
