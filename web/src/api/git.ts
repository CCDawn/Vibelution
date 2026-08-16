import { fetchJson } from "./client";
import type {
  GitCommitMessageResponse,
  GitCommitResponse,
  GitCommitsResponse,
  GitFileDiff,
  GitObjectDetail,
  GitStatusSummary,
} from "./types";

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchGitStatus(options?: {
  limit?: number;
  signal?: AbortSignal;
}): Promise<GitStatusSummary> {
  const limit = options?.limit ?? 500;
  return fetchJson<GitStatusSummary>(`/api/git/status?limit=${limit}`, {
    signal: options?.signal,
  });
}

export function fetchGitCommits(options?: {
  limit?: number;
  signal?: AbortSignal;
}): Promise<GitCommitsResponse> {
  const limit = options?.limit ?? 20;
  return fetchJson<GitCommitsResponse>(`/api/git/commits?limit=${limit}`, {
    signal: options?.signal,
  });
}

export function fetchGitFileDiff(
  path: string,
  options?: { signal?: AbortSignal },
): Promise<GitFileDiff> {
  return fetchJson<GitFileDiff>(`/api/git/diff?path=${encodeURIComponent(path)}`, {
    signal: options?.signal,
  });
}

export function fetchGitObjectDetail(
  params: { kind: string; ref: string; path: string },
  options?: { signal?: AbortSignal },
): Promise<GitObjectDetail> {
  const search = new URLSearchParams({
    kind: params.kind,
    ref: params.ref,
    path: params.path,
  });
  return fetchJson<GitObjectDetail>(`/api/git/object-detail?${search.toString()}`, {
    signal: options?.signal,
  });
}

export function generateGitCommitMessage(payload: {
  paths: string[];
  modelId: string;
}): Promise<GitCommitMessageResponse> {
  return sendJson<GitCommitMessageResponse>("/api/git/commit-message", "POST", payload);
}

export function updateGitCommitMessageDefaultModel(payload: {
  modelId: string;
}): Promise<{ modelId: string; previousModelId: string }> {
  return sendJson<{ modelId: string; previousModelId: string }>(
    "/api/git/commit-message/default-model",
    "PUT",
    payload,
  );
}

export function updateGitCommitMessagePrompt(payload: {
  prompt: string;
}): Promise<{ prompt: string; previousPromptChars: number; promptChars: number }> {
  return sendJson<{ prompt: string; previousPromptChars: number; promptChars: number }>(
    "/api/git/commit-message/prompt",
    "PUT",
    payload,
  );
}

export function createGitCommit(payload: {
  paths: string[];
  message: string;
}): Promise<GitCommitResponse> {
  return sendJson<GitCommitResponse>("/api/git/commit", "POST", payload);
}
