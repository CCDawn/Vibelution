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

function writeJson<T>(url: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function listDataProcessingProfiles<T>(options?: { signal?: AbortSignal }): Promise<T> {
  return fetchJson<T>("/api/data-processing/profiles", { signal: options?.signal });
}

export function fetchDataProcessingProfile<T>(
  profileId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/data-processing/profiles/${encodeURIComponent(profileId)}`,
    { signal: options?.signal },
  );
}

export function createDataProcessingRun<T>(body: unknown): Promise<T> {
  return writeJson<T>("/api/data-processing/runs", body);
}

export function fetchDataProcessingRun<T>(
  runId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}`,
    { signal: options?.signal },
  );
}

export function addDataProcessingRecord<T>(runId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/records`,
    body,
  );
}

export function createDataProcessingCollectionAssignment<T>(runId: string, body: unknown): Promise<T> {
  return writeJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/collection-assignments`,
    body,
  );
}

export function recordDataProcessingCollectionOutput<T>(
  runId: string,
  assignmentId: string,
  body: unknown,
): Promise<T> {
  return writeJson<T>(
    `/api/data-processing/runs/${encodeURIComponent(runId)}/collection-assignments/${encodeURIComponent(assignmentId)}/outputs`,
    body,
  );
}
