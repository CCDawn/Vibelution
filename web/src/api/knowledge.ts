import { fetchJson } from "./client";

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function commaList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function agentQuery(
  agentId?: string,
  extra: Record<string, string | number | undefined> = {},
): string {
  const params = new URLSearchParams();
  if (agentId?.trim()) {
    params.set("agentId", agentId.trim());
  }
  for (const [key, value] of Object.entries(extra)) {
    if (value === undefined || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

function knowledgeBasePath(knowledgeBaseId: string, suffix: string): string {
  return `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}${suffix}`;
}

export function fetchKnowledgeOverview<T>(options?: {
  agentId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(`/api/knowledge/overview${agentQuery(options?.agentId)}`, {
    signal: options?.signal,
  });
}

export function fetchKnowledgeDashboardSnapshot<T>(options: {
  agentId: string;
  recommendationLimit?: number;
  workbenchLimit?: number;
  planLimit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(
    `/api/knowledge/dashboard-snapshot?${new URLSearchParams({
      recommendationLimit: String(options.recommendationLimit ?? 6),
      workbenchLimit: String(options.workbenchLimit ?? 8),
      planLimit: String(options.planLimit ?? 8),
      agentId: options.agentId,
    }).toString()}`,
    { signal: options.signal },
  );
}

export function fetchKnowledgeStewardOverview<T>(options?: {
  agentId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(`/api/knowledge/steward/overview${agentQuery(options?.agentId)}`, {
    signal: options?.signal,
  });
}

export function fetchKnowledgeStewardRecommendations<T>(options?: {
  agentId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(
    `/api/knowledge/steward/recommendations${agentQuery(options?.agentId, { limit: options?.limit })}`,
    { signal: options?.signal },
  );
}

export function fetchKnowledgeStewardWorkbench<T>(options?: {
  agentId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(
    `/api/knowledge/steward/workbench${agentQuery(options?.agentId, { limit: options?.limit })}`,
    { signal: options?.signal },
  );
}

export function fetchKnowledgeOperationsHealth<T>(options?: {
  agentId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(`/api/knowledge/operations/health${agentQuery(options?.agentId)}`, {
    signal: options?.signal,
  });
}

export function fetchKnowledgeAgentReadiness<T>(options?: {
  agentId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(`/api/knowledge/agent-readiness${agentQuery(options?.agentId)}`, {
    signal: options?.signal,
  });
}

export function fetchKnowledgeGovernancePlan<T>(options?: {
  agentId?: string;
  limit?: number;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(
    `/api/knowledge/governance/plan${agentQuery(options?.agentId, { limit: options?.limit })}`,
    { signal: options?.signal },
  );
}

export function searchKnowledgeItems<T>(options: {
  agentId: string;
  knowledgeBaseId?: string;
  query?: string;
  tags?: string;
  searchMode?: string;
  limit?: number;
  teamId?: string;
  ownerType?: string;
  ownerId?: string;
  sourceType?: string;
  importanceLevel?: string;
  confidenceMin?: string;
  stability?: string;
  createdFrom?: string;
  createdTo?: string;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  params.set("agentId", options.agentId);
  if (options.knowledgeBaseId) {
    params.set("knowledgeBaseId", options.knowledgeBaseId);
  }
  if (options.query?.trim()) {
    params.set("query", options.query.trim());
  }
  commaList(options.tags ?? "").forEach((tag) => params.append("tags", tag));
  params.set("searchMode", options.searchMode ?? "keyword");
  params.set("limit", String(options.limit ?? 12));
  if (options.teamId) {
    params.set("teamId", options.teamId);
  }
  if (options.ownerType) {
    params.set("ownerType", options.ownerType);
  }
  if (options.ownerId) {
    params.set("ownerId", options.ownerId);
  }
  if (options.sourceType) {
    params.set("sourceType", options.sourceType);
  }
  if (options.importanceLevel) {
    params.set("importanceLevel", options.importanceLevel);
  }
  if (options.confidenceMin) {
    params.set("confidenceMin", options.confidenceMin);
  }
  if (options.stability) {
    params.set("stability", options.stability);
  }
  if (options.createdFrom) {
    params.set("createdFrom", options.createdFrom);
  }
  if (options.createdTo) {
    params.set("createdTo", options.createdTo);
  }
  return fetchJson<T>(`/api/knowledge/search?${params.toString()}`, { signal: options.signal });
}

export function retrieveKnowledgeRag<T>(options: {
  agentId: string;
  knowledgeBaseId?: string;
  query?: string;
  tags?: string;
  retrievalMode?: string;
  provider?: string;
  topK?: number;
  maxContextChars?: number;
  teamId?: string;
  ownerType?: string;
  ownerId?: string;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams();
  params.set("agentId", options.agentId);
  if (options.knowledgeBaseId) {
    params.set("knowledgeBaseId", options.knowledgeBaseId);
  }
  if (options.query?.trim()) {
    params.set("query", options.query.trim());
  }
  commaList(options.tags ?? "").forEach((tag) => params.append("tags", tag));
  params.set("retrievalMode", options.retrievalMode ?? "keyword");
  params.set("provider", options.provider ?? "local");
  params.set("topK", String(options.topK ?? 6));
  params.set("maxContextChars", String(options.maxContextChars ?? 4000));
  if (options.teamId) {
    params.set("teamId", options.teamId);
  }
  if (options.ownerType) {
    params.set("ownerType", options.ownerType);
  }
  if (options.ownerId) {
    params.set("ownerId", options.ownerId);
  }
  return fetchJson<T>(`/api/knowledge/rag/retrieve?${params.toString()}`, { signal: options.signal });
}

export function fetchKnowledgeRagHealth<T>(options: {
  agentId: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(`/api/knowledge/rag/health?${new URLSearchParams({ agentId: options.agentId }).toString()}`, {
    signal: options.signal,
  });
}

export function collectKnowledgeSourceInbox<T>(body: unknown): Promise<T> {
  return sendJson<T>("/api/knowledge/sources/inbox", "POST", body);
}

export function listKnowledgeSourceInbox<T>(options: {
  ownerType: string;
  ownerId: string;
  agentId: string;
  status?: string;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams({
    ownerType: options.ownerType,
    ownerId: options.ownerId,
    agentId: options.agentId,
  });
  if (options.status) {
    params.set("status", options.status);
  }
  return fetchJson<T>(`/api/knowledge/sources/inbox?${params.toString()}`, { signal: options.signal });
}

export function reviewKnowledgeSourceInbox<T>(
  ownerType: string,
  ownerId: string,
  inboxSourceId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    `/api/knowledge/sources/inbox/${encodeURIComponent(ownerType)}/${encodeURIComponent(ownerId)}/${encodeURIComponent(inboxSourceId)}/review`,
    "PATCH",
    body,
  );
}

export function updateKnowledgeSourceGovernance<T>(
  ownerType: string,
  ownerId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    `/api/knowledge/sources/governance/${encodeURIComponent(ownerType)}/${encodeURIComponent(ownerId)}`,
    "PUT",
    body,
  );
}

export function listKnowledgeCentralSources<T>(options: {
  agentId: string;
  ownerType: string;
  ownerId: string;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams({
    agentId: options.agentId,
    ownerType: options.ownerType,
    ownerId: options.ownerId,
  });
  return fetchJson<T>(`/api/knowledge/sources/registry?${params.toString()}`, { signal: options.signal });
}

export function fetchKnowledgePermissionAudit<T>(options: {
  agentId: string;
  signal?: AbortSignal;
}): Promise<T> {
  return fetchJson<T>(
    `/api/knowledge/permissions/audit?agentId=${encodeURIComponent(options.agentId)}`,
    { signal: options.signal },
  );
}

export function fetchKnowledgeGovernanceTasks<T>(options: {
  agentId: string;
  status?: string;
  signal?: AbortSignal;
}): Promise<T> {
  const params = new URLSearchParams({ agentId: options.agentId });
  if (options.status) {
    params.set("status", options.status);
  }
  return fetchJson<T>(`/api/knowledge/governance/tasks?${params.toString()}`, { signal: options.signal });
}

export function listKnowledgeIngestionAdapters<T>(options?: { signal?: AbortSignal }): Promise<T> {
  return fetchJson<T>("/api/knowledge/ingestion-adapters", { signal: options?.signal });
}

export function listTeamKnowledgeBases<T>(
  teamId: string,
  options?: { agentId?: string; signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/teams/${encodeURIComponent(teamId)}/knowledge-bases${agentQuery(options?.agentId)}`,
    { signal: options?.signal },
  );
}

export function createTeamKnowledgeBase<T>(teamId: string, body: unknown): Promise<T> {
  return sendJson<T>(`/api/teams/${encodeURIComponent(teamId)}/knowledge-bases`, "POST", body);
}

export function listAgentKnowledgeBases<T>(
  agentId: string,
  options?: { actorAgentId?: string; signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `/api/agents/${encodeURIComponent(agentId)}/knowledge-bases${agentQuery(undefined, {
      actorAgentId: options?.actorAgentId,
    })}`,
    { signal: options?.signal },
  );
}

export function createAgentKnowledgeBase<T>(agentId: string, body: unknown): Promise<T> {
  return sendJson<T>(`/api/agents/${encodeURIComponent(agentId)}/knowledge-bases`, "POST", body);
}

export function createKnowledgeCentralSourceArtifact<T>(
  knowledgeBaseId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(knowledgeBasePath(knowledgeBaseId, "/central-source-artifacts"), "POST", body);
}

export function createKnowledgeRefinementProposal<T>(
  knowledgeBaseId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(knowledgeBasePath(knowledgeBaseId, "/refinement-proposals"), "POST", body);
}

export function createKnowledgeIngestionPackage<T>(
  knowledgeBaseId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(knowledgeBasePath(knowledgeBaseId, "/ingestion-packages"), "POST", body);
}

export function reviewKnowledgeRefinementProposal<T>(
  knowledgeBaseId: string,
  proposalId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    knowledgeBasePath(
      knowledgeBaseId,
      `/refinement-proposals/${encodeURIComponent(proposalId)}/review`,
    ),
    "PATCH",
    body,
  );
}

export function listKnowledgeItems<T>(
  knowledgeBaseId: string,
  options: { agentId?: string; signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `${knowledgeBasePath(knowledgeBaseId, "/items")}${agentQuery(options.agentId)}`,
    { signal: options.signal },
  );
}

export function fetchKnowledgeTrace<T>(
  knowledgeBaseId: string,
  targetId: string,
  options: { agentId?: string; signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `${knowledgeBasePath(knowledgeBaseId, `/trace/${encodeURIComponent(targetId)}`)}${agentQuery(options.agentId)}`,
    { signal: options.signal },
  );
}

export function updateKnowledgeItemRating<T>(
  knowledgeBaseId: string,
  knowledgeItemId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    knowledgeBasePath(knowledgeBaseId, `/items/${encodeURIComponent(knowledgeItemId)}/rating`),
    "PATCH",
    body,
  );
}

export function listKnowledgeRatingSuggestions<T>(
  knowledgeBaseId: string,
  options: { agentId?: string; status?: string; signal?: AbortSignal },
): Promise<T> {
  return fetchJson<T>(
    `${knowledgeBasePath(knowledgeBaseId, "/rating-suggestions")}${agentQuery(options.agentId, {
      status: options.status,
    })}`,
    { signal: options.signal },
  );
}

export function createKnowledgeRatingSuggestion<T>(
  knowledgeBaseId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(knowledgeBasePath(knowledgeBaseId, "/rating-suggestions"), "POST", body);
}

export function reviewKnowledgeRatingSuggestion<T>(
  knowledgeBaseId: string,
  suggestionId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    knowledgeBasePath(
      knowledgeBaseId,
      `/rating-suggestions/${encodeURIComponent(suggestionId)}/review`,
    ),
    "PATCH",
    body,
  );
}

export function bulkReviewKnowledgeRatingSuggestions<T>(
  knowledgeBaseId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(
    knowledgeBasePath(knowledgeBaseId, "/rating-suggestions/review-batch"),
    "PATCH",
    body,
  );
}
