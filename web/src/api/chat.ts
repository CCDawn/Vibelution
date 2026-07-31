import { fetchJson } from "./client";
import type { SessionToolApprovalRequest } from "./types";

export type SessionToolApprovalDecision = "accept" | "acceptForSession" | "decline";

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
