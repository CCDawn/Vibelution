import { fetchJson } from "./client";
import type {
  ChatRoomDetail,
  ChatRoomMode,
  ChatRoomPurpose,
  ChatRoomRoundAcceptedResponse,
  ChatWorkbenchBootstrap,
  ConversationAttachment,
  ConversationSummary,
  SessionChatReviewCandidateResponse,
  SessionDeleteResponse,
  SessionBulkDeleteResponse,
  SessionDetail,
  SessionGuidanceMode,
  SessionLlmOptions,
  SessionQueryResponse,
  SessionSummary,
  SessionToolApprovalRequest,
  SessionTurnAcceptedResponse,
} from "./types";

export function isSessionNotFoundError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error ?? "");
  return /session not found|会话不存在|未找到会话|未找到当前会话/i.test(message);
}

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

export function listSessionChildSessions(sessionId: string): Promise<SessionSummary[]> {
  return fetchJson<SessionSummary[]>(
    `/api/sessions/${encodeURIComponent(sessionId)}/child-sessions`,
  );
}

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

export function listConversations(): Promise<ConversationSummary[]> {
  return fetchJson<ConversationSummary[]>("/api/conversations");
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

export async function deleteChatSession(sessionId: string): Promise<SessionDeleteResponse> {
  try {
    return await fetchJson<SessionDeleteResponse>(`/api/sessions/${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: {
        Prefer: "respond-async",
      },
    });
  } catch (error) {
    if (isSessionNotFoundError(error)) {
      return {
        deleted: true,
        deletedSessionId: sessionId,
        nextActiveSessionId: "",
      };
    }
    throw error;
  }
}

export function bulkDeleteChatSessions(sessionIds: string[]): Promise<SessionBulkDeleteResponse> {
  return fetchJson<SessionBulkDeleteResponse>("/api/sessions/bulk-delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sessionIds }),
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

export function listChatRoomModes(): Promise<ChatRoomMode[]> {
  return fetchJson<ChatRoomMode[]>("/api/chat-rooms/modes");
}

export function listChatRoomPurposes(): Promise<ChatRoomPurpose[]> {
  return fetchJson<ChatRoomPurpose[]>("/api/chat-rooms/purposes");
}

export function fetchChatRoomDetail(
  roomId: string,
  options?: { signal?: AbortSignal },
): Promise<ChatRoomDetail> {
  return fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(roomId)}`, {
    signal: options?.signal,
  });
}

export function createChatRoom(payload: {
  title: string;
  agentIds: string[];
  mode: string;
  purpose: string;
}): Promise<ChatRoomDetail> {
  const { title, agentIds, mode, purpose } = payload;
  return fetchJson<ChatRoomDetail>("/api/chat-rooms", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title, agentIds, mode, purpose }),
  });
}

export function updateChatRoom(
  roomId: string,
  payload: {
    title: string;
    participantSessionIds: string[];
    mode: string;
    purpose: string;
  },
): Promise<ChatRoomDetail> {
  return fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(roomId)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      title: payload.title,
      participantSessionIds: payload.participantSessionIds,
      mode: payload.mode,
      purpose: payload.purpose,
    }),
  });
}

export type ChatRoomDeleteResponse = {
  deleted: boolean;
  roomId: string;
};

export function deleteChatRoom(roomId: string): Promise<ChatRoomDeleteResponse> {
  return fetchJson<ChatRoomDeleteResponse>(`/api/chat-rooms/${encodeURIComponent(roomId)}`, {
    method: "DELETE",
  });
}

export function resetChatRoom(roomId: string): Promise<ChatRoomDetail> {
  return fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(roomId)}/reset`, {
    method: "POST",
  });
}

export function stopChatRoomRound(roomId: string): Promise<ChatRoomDetail> {
  return fetchJson<ChatRoomDetail>(`/api/chat-rooms/${encodeURIComponent(roomId)}/stop`, {
    method: "POST",
  });
}

export function startChatRoomRound(
  roomId: string,
  payload: {
    topic: string;
    mode: string;
    purpose: string;
    config?: Record<string, unknown>;
  },
  options: { preferAsync: true },
): Promise<ChatRoomRoundAcceptedResponse>;
export function startChatRoomRound(
  roomId: string,
  payload: {
    topic: string;
    mode: string;
    purpose: string;
    config?: Record<string, unknown>;
  },
  options?: { preferAsync?: false },
): Promise<ChatRoomDetail>;
export function startChatRoomRound(
  roomId: string,
  payload: {
    topic: string;
    mode: string;
    purpose: string;
    config?: Record<string, unknown>;
  },
  options?: { preferAsync?: boolean },
): Promise<ChatRoomDetail | ChatRoomRoundAcceptedResponse> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (options?.preferAsync) {
    headers.Prefer = "respond-async";
  }
  return fetchJson<ChatRoomDetail | ChatRoomRoundAcceptedResponse>(
    `/api/chat-rooms/${encodeURIComponent(roomId)}/rounds`,
    {
      method: "POST",
      headers,
      body: JSON.stringify({
        topic: payload.topic,
        mode: payload.mode,
        purpose: payload.purpose,
        ...(payload.config == null ? {} : { config: payload.config }),
      }),
    },
  );
}
