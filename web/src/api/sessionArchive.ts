import { fetchJson } from "./client";
import type { SessionSummary } from "./types";

/**
 * Session-level archive API (ZCode-style lightweight archive).
 *
 * Archive is a pure metadata flip on the backend (archiveState + directory
 * index seal); session data files stay untouched and the flip is reversible.
 */

export type SessionArchiveCommandResponse = {
  sessionId: string;
  status: string;
  changed: boolean;
  archivedAt?: string;
  readOnly?: boolean;
};

export type SessionArchiveListResponse = {
  items: SessionSummary[];
  nextCursor: string;
  totalEstimate: number;
};

export async function archiveChatSession(
  sessionId: string,
  options?: { signal?: AbortSignal },
): Promise<SessionArchiveCommandResponse> {
  return await fetchJson<SessionArchiveCommandResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/archive`,
    { method: "POST", signal: options?.signal },
  );
}

export async function unarchiveChatSession(
  sessionId: string,
  options?: { signal?: AbortSignal },
): Promise<SessionArchiveCommandResponse> {
  return await fetchJson<SessionArchiveCommandResponse>(
    `/api/sessions/${encodeURIComponent(sessionId)}/unarchive`,
    { method: "POST", signal: options?.signal },
  );
}

export async function listArchivedChatSessions(
  options?: { signal?: AbortSignal; limit?: number; cursor?: string },
): Promise<SessionArchiveListResponse> {
  const params = new URLSearchParams();
  if (options?.limit) {
    params.set("limit", String(options.limit));
  }
  if (options?.cursor) {
    params.set("cursor", options.cursor);
  }
  const suffix = params.toString();
  return await fetchJson<SessionArchiveListResponse>(
    suffix ? `/api/session-archive?${suffix}` : "/api/session-archive",
    { signal: options?.signal },
  );
}
