import { fetchJson } from "./client";
import type {
  SessionChatReviewCandidateResponse,
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
