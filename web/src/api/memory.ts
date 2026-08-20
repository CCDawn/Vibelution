import { fetchJson } from "./client";
import type {
  MemoryCleanupExecuteResponse,
  MemoryCleanupPreviewResponse,
  MemoryItemDetailPayload,
  MemoryMutationResponse,
  MemoryOverview,
  MemoryUsageContractPayload,
  GithubProjectLibraryMutationResponse,
  GithubProjectLibraryPayload,
} from "./types";

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function memoryItemPath(sectionId: string, itemId: string, suffix = ""): string {
  return `/api/memory/items/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}${suffix}`;
}

export function fetchMemoryOverview<T = MemoryOverview>(options?: {
  includeContent?: boolean;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  if (options?.includeContent !== undefined) {
    params.set("includeContent", String(options.includeContent));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<T>(`/api/memory/overview${suffix}`, { signal: options?.signal });
}

export function fetchMemoryUsageContract<T = MemoryUsageContractPayload>(options?: {
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>("/api/memory/usage-contract", { signal: options?.signal });
}

export function fetchMemoryAgents<T>(options?: {
  agentId?: string;
  includeContent?: boolean;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  if (options?.agentId?.trim()) {
    params.set("agentId", options.agentId.trim());
  }
  if (options?.includeContent !== undefined) {
    params.set("includeContent", String(options.includeContent));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<T>(`/api/memory/agents${suffix}`, { signal: options?.signal });
}

export function fetchMemoryAgentDetail<T>(
  agentId: string,
  options?: { actorAgentId?: string; includeContent?: boolean; signal?: AbortSignal },
): Promise<T> {
  const params = new URLSearchParams();
  if (options?.actorAgentId) {
    params.set("actorAgentId", options.actorAgentId);
  }
  if (options?.includeContent !== undefined) {
    params.set("includeContent", String(options.includeContent));
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<T>(`/api/memory/agents/${encodeURIComponent(agentId)}${suffix}`, {
    signal: options?.signal,
  });
}

export function fetchMemoryKnowledgeGraph<T>(options: {
  agentId: string;
  include?: string;
  teamId?: string;
  knowledgeBaseId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  const agentId = options.agentId.trim();
  if (agentId) {
    params.set("agentId", agentId);
  }
  if (options.include) {
    params.set("include", options.include);
  }
  if (options.teamId) {
    params.set("teamId", options.teamId);
  }
  if (options.knowledgeBaseId) {
    params.set("knowledgeBaseId", options.knowledgeBaseId);
  }
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  return fetchJson<T>(`/api/memory/knowledge-graph?${params.toString()}`, {
    signal: options.signal,
  });
}

export function fetchMemoryKnowledgeGraphNodeDetail<T>(options: {
  nodeId: string;
  agentId: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams({ nodeId: options.nodeId });
  const agentId = options.agentId.trim();
  if (agentId) {
    params.set("agentId", agentId);
  }
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  return fetchJson<T>(`/api/memory/knowledge-graph/node-detail?${params.toString()}`, {
    signal: options.signal,
  });
}

export function fetchMemoryItemDetail<T = MemoryItemDetailPayload>(
  sectionId: string,
  itemId: string,
  options?: { signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(memoryItemPath(sectionId, itemId), { signal: options?.signal });
}

export function createMemoryItem<T = MemoryMutationResponse>(body: {
  title: string;
  summary: string;
  content: string;
}): Promise<T> {
  return sendJson<T>("/api/memory/items", "POST", body);
}

export function updateMemoryItem<T = MemoryMutationResponse>(
  sectionId: string,
  itemId: string,
  body: { title: string; summary: string; content: string },
): Promise<T> {
  return sendJson<T>(memoryItemPath(sectionId, itemId), "PATCH", body);
}

export function deleteMemoryItem<T = MemoryMutationResponse>(
  sectionId: string,
  itemId: string,
): Promise<T> {
  return fetchJson<T>(memoryItemPath(sectionId, itemId), { method: "DELETE" });
}

export function restoreMemoryItem<T = MemoryMutationResponse>(
  sectionId: string,
  itemId: string,
): Promise<T> {
  return sendJson<T>(memoryItemPath(sectionId, itemId, "/restore"), "POST");
}

export function previewMemoryCleanup<T = MemoryCleanupPreviewResponse>(
  targets: Array<Record<string, unknown>>,
): Promise<T> {
  return sendJson<T>("/api/memory/cleanup/preview", "POST", { targets });
}

export function executeMemoryCleanup<T = MemoryCleanupExecuteResponse>(body: {
  targets: Array<Record<string, unknown>>;
  confirmationPhrase: string;
  previewToken: string;
}): Promise<T> {
  return sendJson<T>("/api/memory/cleanup/execute", "POST", body);
}

export function fetchGithubProjectLibrary<T = GithubProjectLibraryPayload>(options?: {
  query?: string;
  includeArchived?: boolean;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  if (options?.query?.trim()) {
    params.set("query", options.query.trim());
  }
  if (options?.includeArchived) {
    params.set("includeArchived", "true");
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<T>(`/api/memory/github-projects${suffix}`, { signal: options?.signal });
}

export function cloneGithubProject<T = GithubProjectLibraryMutationResponse>(body: {
  spec: string;
  confirm?: boolean;
  action?: "clone" | "fetch";
}): Promise<T> {
  return sendJson<T>("/api/memory/github-projects", "POST", body);
}
