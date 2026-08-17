import { fetchJson } from "./client";
import type {
  EvolutionChatReviewBulkDeleteResponse,
  EvolutionChatReviewCandidate,
  EvolutionChatReviewDecisionResponse,
  EvolutionChatReviewQueue,
  EvolutionOverview,
  EvolutionProposalBulkDeleteResponse,
  EvolutionProposalDeleteResponse,
  EvolutionProposalDetail,
  EvolutionProposalUpdateResponse,
  EvolutionRunActionResponse,
  EvolutionWorkbench,
  EvolutionWorkspaceSnapshot,
  SelfEvolutionHistoryDeleteResponse,
  SelfEvolutionWorkspaceSnapshot,
  SelfObservationRun,
  SupervisedWorktreeRun,
} from "./types";

function sendJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export function fetchEvolutionOverview<T = EvolutionOverview>(): Promise<T> {
  return fetchJson<T>("/api/evolution/overview");
}

export function fetchEvolutionWorkspaceSnapshot<T = EvolutionWorkspaceSnapshot>(): Promise<T> {
  return fetchJson<T>("/api/evolution/workspace-snapshot");
}

export function fetchEvolutionWorkbench<T = EvolutionWorkbench>(): Promise<T> {
  return fetchJson<T>("/api/evolution/workbench");
}

export function fetchSelfEvolutionWorkspaceSnapshot<T = SelfEvolutionWorkspaceSnapshot>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/workspace-snapshot");
}

export function fetchSelfObservationRun<T = SelfObservationRun>(runId: string): Promise<T> {
  return fetchJson<T>(
    `/api/evolution/self/observation-runs/${encodeURIComponent(runId)}`,
  );
}

export function fetchEvolutionProposalDetail<T = EvolutionProposalDetail>(
  sessionId: string,
): Promise<T> {
  return fetchJson<T>(`/api/evolution/proposals/${sessionId}`);
}

export function updateEvolutionProposal<T = EvolutionProposalUpdateResponse>(
  sessionId: string,
  draft: Record<string, unknown>,
): Promise<T> {
  return sendJson<T>(`/api/evolution/proposals/${sessionId}`, "PATCH", draft);
}

export function deleteEvolutionProposal<T = EvolutionProposalDeleteResponse>(
  sessionId: string,
): Promise<T> {
  return fetchJson<T>(`/api/evolution/proposals/${sessionId}`, { method: "DELETE" });
}

export function bulkDeleteEvolutionProposals<T = EvolutionProposalBulkDeleteResponse>(
  sessionIds: string[],
): Promise<T> {
  return sendJson<T>("/api/evolution/proposals/delete", "POST", { sessionIds });
}

export function createEvolutionWorktreeRun<T = SupervisedWorktreeRun>(
  body: unknown,
): Promise<T> {
  return sendJson<T>("/api/evolution/worktree-runs", "POST", body);
}

export function createSelfEvolutionWorktreeRun<T = SupervisedWorktreeRun>(
  body: unknown,
): Promise<T> {
  return sendJson<T>("/api/evolution/self/worktree-runs", "POST", body);
}

export function startSelfObservationRun<T = SelfObservationRun>(body: unknown): Promise<T> {
  return sendJson<T>("/api/evolution/self/observation-runs", "POST", body);
}

export function postSelfObservationRunAction<T = SelfObservationRun>(
  runId: string,
  action: string,
): Promise<T> {
  return sendJson<T>(
    `/api/evolution/self/observation-runs/${encodeURIComponent(runId)}/actions`,
    "POST",
    { action },
  );
}

export function deleteSelfEvolutionHistory<T = SelfEvolutionHistoryDeleteResponse>(
  txnIds: string[],
): Promise<T> {
  return sendJson<T>("/api/evolution/self/history/delete", "POST", { txnIds });
}

export function postEvolutionRunAction<T = EvolutionRunActionResponse>(
  sessionId: string,
  action: string,
): Promise<T> {
  return sendJson<T>(`/api/evolution/runs/${sessionId}/actions`, "POST", { action });
}

export function postEvolutionWorktreeRunAction<T = SupervisedWorktreeRun>(
  runId: string,
  body: { action: string; reviewerNote?: string },
): Promise<T> {
  return sendJson<T>(
    `/api/evolution/worktree-runs/${encodeURIComponent(runId)}/actions`,
    "POST",
    {
      action: body.action,
      reviewerNote: body.reviewerNote ?? "",
    },
  );
}

export function fetchEvolutionChatReviewQueue<T = EvolutionChatReviewQueue>(): Promise<T> {
  return fetchJson<T>("/api/evolution/chat-review");
}

export function fetchEvolutionChatReviewCandidate<T = EvolutionChatReviewCandidate>(
  candidateId: string,
): Promise<T> {
  return fetchJson<T>(
    `/api/evolution/chat-review/${encodeURIComponent(candidateId)}`,
  );
}

export function decideEvolutionChatReview<T = EvolutionChatReviewDecisionResponse>(
  candidateId: string,
  body: unknown,
): Promise<T> {
  return sendJson<T>(`/api/evolution/chat-review/${candidateId}/decision`, "POST", body);
}

export function bulkDeleteEvolutionChatReview<T = EvolutionChatReviewBulkDeleteResponse>(
  body: unknown,
): Promise<T> {
  return sendJson<T>("/api/evolution/chat-review/delete", "POST", body);
}

export function fetchEvolutionRuns<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/runs");
}

export function fetchEvolutionLibrary<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/library");
}

export function fetchEvolutionChatReviewApprove<T>(candidateId: string, body?: unknown): Promise<T> {
  return sendJson<T>(
    `/api/evolution/chat-review/${encodeURIComponent(candidateId)}/approve`,
    "POST",
    body,
  );
}

export function fetchEvolutionChatReviewReject<T>(candidateId: string, body?: unknown): Promise<T> {
  return sendJson<T>(
    `/api/evolution/chat-review/${encodeURIComponent(candidateId)}/reject`,
    "POST",
    body,
  );
}

export function fetchEvolutionActiveRun<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/active-run");
}

export function fetchEvolutionLatestRun<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/latest-run");
}

export function fetchEvolutionRunCommand<T>(commandId: string): Promise<T> {
  return fetchJson<T>(`/api/evolution/runs/commands/${encodeURIComponent(commandId)}`);
}

export function listEvolutionWorktreeRuns<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/worktree-runs");
}

export function fetchEvolutionWorktreeActiveRun<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/worktree-runs/active");
}

export function fetchEvolutionWorktreeRun<T>(runId: string): Promise<T> {
  return fetchJson<T>(`/api/evolution/worktree-runs/${encodeURIComponent(runId)}`);
}

export function startEvolutionRun<T>(body: unknown): Promise<T> {
  return sendJson<T>("/api/evolution/runs", "POST", body);
}

export function pauseEvolutionRun<T>(runId: string): Promise<T> {
  return sendJson<T>(`/api/evolution/runs/${encodeURIComponent(runId)}/pause`, "POST");
}

export function resumeEvolutionRun<T>(runId: string): Promise<T> {
  return sendJson<T>(`/api/evolution/runs/${encodeURIComponent(runId)}/resume`, "POST");
}

export function retryEvolutionRun<T>(runId: string): Promise<T> {
  return sendJson<T>(`/api/evolution/runs/${encodeURIComponent(runId)}/retry`, "POST");
}

export function terminateEvolutionRun<T>(runId: string): Promise<T> {
  return sendJson<T>(`/api/evolution/runs/${encodeURIComponent(runId)}/terminate`, "POST");
}

export function deleteEvolutionRun<T>(runId: string): Promise<T> {
  return fetchJson<T>(`/api/evolution/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

export function fetchSelfEvolutionOverview<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/overview");
}

export function fetchSelfEvolutionTransactions<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/transactions");
}

export function fetchSelfEvolutionAudit<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/audit");
}

export function fetchSelfEvolutionCandidates<T>(): Promise<T> {
  return fetchJson<T>("/api/evolution/self/candidates");
}
