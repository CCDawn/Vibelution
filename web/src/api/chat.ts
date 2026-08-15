import { fetchJson } from "./client";
import type {
  ChatWorkbenchBootstrap,
  SessionChatReviewCandidateResponse,
  SessionDeleteResponse,
  SessionDetail,
  SessionQueryResponse,
  SessionSummary,
  SessionToolApprovalRequest,
} from "./types";

export type SessionToolApprovalDecision =
  | "accept"
  | "acceptForSession"
  | "acceptAlways"
  | "decline";

export function listPendingSessionToolApprovals(
  sessionId: string,
): Promise<SessionToolApprovalRequest[]> {
  return fetchJson<SessionToolApprovalRequest[]>(
    `/api/sessions/${encodeURIComponent(sessionId)}/tool-approvals?status=pending`,
  );
}

export function resolveSessionToolApprovalDecision(
  request: SessionToolApprovalRequest,
  decision: SessionToolApprovalDecision,
): Promise<SessionToolApprovalRequest> {
  return fetchJson<SessionToolApprovalRequest>(
    `/api/sessions/${encodeURIComponent(request.sessionId)}/tool-approvals/${encodeURIComponent(request.requestId)}/decision`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ decision }),
    },
  );
}

/**
 * Adds a completed chat session to the human review queue.
 * Keep this request in the chat API boundary instead of a route lifecycle hook.
 */
export function createSessionChatReviewCandidate(
  sessionId: string,
): Promise<SessionChatReviewCandidateResponse> {
  return fetchJson<SessionChatReviewCandidateResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/chat-review-candidate`,
    { method: "POST" },
  );
}

export type SessionQueryParams = {
  limit?: number;
  cursor?: string;
  q?: string;
  agentId?: string;
  sessionKind?: string;
  state?: string;
  sort?: string;
};

export function querySessions(params: SessionQueryParams = {}): Promise<SessionQueryResponse> {
  const search = new URLSearchParams();
  if (params.limit != null) {
    search.set("limit", String(params.limit));
  }
  if (params.cursor) {
    search.set("cursor", params.cursor);
  }
  if (params.q) {
    search.set("q", params.q);
  }
  if (params.agentId) {
    search.set("agentId", params.agentId);
  }
  if (params.sessionKind) {
    search.set("sessionKind", params.sessionKind);
  }
  if (params.state) {
    search.set("state", params.state);
  }
  if (params.sort) {
    search.set("sort", params.sort);
  }
  const suffix = search.toString();
  return fetchJson<SessionQueryResponse>(
    suffix ? `/api/sessions/query?${suffix}` : "/api/sessions/query",
  );
}

export function fetchChatWorkbenchBootstrap(init?: {
  signal?: AbortSignal;
}): Promise<ChatWorkbenchBootstrap> {
  return fetchJson<ChatWorkbenchBootstrap>("/api/sessions/bootstrap?limit=50", {
    signal: init?.signal,
  });
}

export function getActiveSession(): Promise<{ activeSessionId: string }> {
  return fetchJson<{ activeSessionId: string }>("/api/sessions/active");
}

export function listSessions(): Promise<SessionSummary[]> {
  return fetchJson<SessionSummary[]>("/api/sessions");
}

export function createChatSession(payload: {
  agentId?: string;
  title?: string;
}): Promise<SessionDetail> {
  return fetchJson<SessionDetail>("/api/sessions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Prefer: "respond-async",
    },
    body: JSON.stringify(payload),
  });
}

export function selectChatSession(sessionId: string): Promise<SessionDetail> {
  return fetchJson<SessionDetail>(
    `/api/sessions/${encodeURIComponent(sessionId)}/select`,
    {
      method: "POST",
      headers: { Prefer: "respond-async" },
    },
  );
}

export function updateChatSession(
  sessionId: string,
  payload: { title?: string; agentId?: string },
): Promise<SessionDetail> {
  return fetchJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function deleteChatSession(sessionId: string): Promise<SessionDeleteResponse> {
  return fetchJson<SessionDeleteResponse>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: {
      Prefer: "respond-async",
    },
  });
}
