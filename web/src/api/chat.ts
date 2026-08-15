import { fetchJson } from "./client";
import type {
  ChatWorkbenchBootstrap,
  ConversationAttachment,
  SessionChatReviewCandidateResponse,
  SessionDeleteResponse,
  SessionDetail,
  SessionGuidanceMode,
  SessionLlmOptions,
  SessionQueryResponse,
  SessionSummary,
  SessionToolApprovalRequest,
  SessionTurnAcceptedResponse,
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

export type SessionDetailQueryOptions = {
  messageLimit?: number;
  beforeMessageIndex?: number;
  transcriptScope?: "all" | "window" | "none";
  includeSecondary?: boolean;
  signal?: AbortSignal;
};

export function fetchSessionDetail(
  sessionId: string,
  options: SessionDetailQueryOptions = {},
): Promise<SessionDetail> {
  const search = new URLSearchParams();
  if (options.messageLimit != null) {
    search.set("messageLimit", String(options.messageLimit));
  }
  if (options.transcriptScope) {
    search.set("transcriptScope", options.transcriptScope);
  }
  if (options.beforeMessageIndex && options.beforeMessageIndex > 0) {
    search.set("beforeMessageIndex", String(options.beforeMessageIndex));
  }
  if (options.includeSecondary === false) {
    search.set("includeSecondary", "false");
  }
  const suffix = search.toString();
  const path = `/api/sessions/${encodeURIComponent(sessionId)}`;
  return fetchJson<SessionDetail>(suffix ? `${path}?${suffix}` : path, {
    signal: options.signal,
  });
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

export function fetchSessionLlmOptions(sessionId: string): Promise<SessionLlmOptions> {
  return fetchJson<SessionLlmOptions>(
    `/api/sessions/${encodeURIComponent(sessionId)}/llm-options`,
  );
}

export function updateSessionReasoningEffort(
  sessionId: string,
  reasoningEffort: string,
): Promise<SessionLlmOptions> {
  return fetchJson<SessionLlmOptions>(
    `/api/sessions/${encodeURIComponent(sessionId)}/reasoning-effort`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoningEffort }),
    },
  );
}

export function uploadSessionImageAttachment(
  sessionId: string,
  init: { contentType?: string; filename: string; body: Blob },
): Promise<ConversationAttachment> {
  return fetchJson<ConversationAttachment>(
    `/api/sessions/${encodeURIComponent(sessionId)}/attachments`,
    {
      method: "POST",
      headers: {
        "Content-Type": init.contentType || "application/octet-stream",
        "X-Vibelution-Filename": encodeURIComponent(init.filename),
      },
      body: init.body,
    },
  );
}

export function submitSessionMessage(
  sessionId: string,
  payload: {
    content: string;
    clientSubmissionId: string;
    contentUtf8Base64: string;
    attachmentIds: string[];
    references: unknown[];
    mentalModelEnabled?: boolean;
    runtimeStatusEnabled?: boolean;
    turnStatusTail?: unknown;
  },
): Promise<SessionTurnAcceptedResponse> {
  return fetchJson<SessionTurnAcceptedResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Prefer: "respond-async",
      },
      body: JSON.stringify(payload),
    },
  );
}

export function editResubmitSessionMessage(
  sessionId: string,
  payload: {
    messageId: string;
    clientSubmissionId: string;
    content: string;
    contentUtf8Base64: string;
    mentalModelEnabled?: boolean;
    runtimeStatusEnabled?: boolean;
    turnStatusTail?: unknown;
  },
): Promise<SessionDetail> {
  return fetchJson<SessionDetail>(
    `/api/sessions/${encodeURIComponent(sessionId)}/messages/edit-resubmit`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
}

export function stopSessionTurn(sessionId: string, turnId: string): Promise<SessionDetail> {
  return fetchJson<SessionDetail>(`/api/sessions/${encodeURIComponent(sessionId)}/stop`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ turnId }),
  });
}

export function submitSessionGuidance(
  sessionId: string,
  payload: { content: string; mode: SessionGuidanceMode },
): Promise<SessionDetail> {
  return fetchJson<SessionDetail>(
    `/api/sessions/${encodeURIComponent(sessionId)}/guidance`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
}
