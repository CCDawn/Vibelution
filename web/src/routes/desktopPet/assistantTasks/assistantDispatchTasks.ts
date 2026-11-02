import type { LauncherAssistantDispatch } from "../../../api/launcherAssistant";

/** Read-only presentation of the existing bounded dispatch feed. This is not a
 * task store, an execution owner, or proof that the user's goal was achieved. */
export type AssistantDispatchTaskState = "running" | "stopping" | "waiting_user" | "awaiting_verification" | "failed" | "stopped" | "unknown";

export type AssistantDispatchTask = {
  id: string;
  dispatchId: string;
  projectId: string | null;
  agentId: string | null;
  nativeTaskId: string | null;
  nativeStatus: string | null;
  title: string;
  resultSummary: string;
  state: AssistantDispatchTaskState;
  shouldPoll: boolean;
  sourceAvailable: boolean;
  receiptBound: boolean;
  conflictingObservations: boolean;
  pendingApprovalCount: number;
  businessAcceptance: "not_evaluated";
};

export type AssistantDispatchTaskFeed = {
  tasks: AssistantDispatchTask[];
  coverage: "bounded_dispatches";
  complete: false;
  sourceAvailable: boolean;
  invalidRecords: number;
  counts: { inProgress: number; waitingUser: number; awaitingVerification: number; failed: number; stopped: number; unknown: number };
};

// Same native vocabulary as core/external_agent/contracts.py; new states stay
// unknown until their authority and control semantics are explicitly adapted.
const ACTIVE = new Set(["queued", "running", "awaiting_approval"]);
const TERMINAL = new Set(["succeeded", "failed", "cancelled", "timed_out"]);

function identity(value: unknown): string | null {
  return typeof value === "string" && value.trim() && value.length <= 256 ? value : null;
}

function boundedText(value: unknown, limit: number): string {
  if (typeof value !== "string") return "";
  const text = value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g, " ").replace(/\s+/g, " ").trim();
  const characters = Array.from(text);
  return characters.length > limit ? `${characters.slice(0, limit - 1).join("")}…` : text;
}

function projectRow(row: LauncherAssistantDispatch, sourceAvailable: boolean): AssistantDispatchTask {
  const projectId = identity(row.projectId);
  const agentId = identity(row.agentId);
  const nativeTaskId = identity(row.nativeTaskId);
  const nativeStatus = identity(row.receipt?.status);
  const bound = Boolean(projectId && nativeTaskId && row.receipt?.taskId === nativeTaskId);
  const current = sourceAvailable && !row.lastError && bound;
  const active = Boolean(current && nativeStatus && ACTIVE.has(nativeStatus));
  const pending = new Set(active ? row.receipt?.pendingApprovals?.filter(approval => identity(approval.approvalId)
    && identity(approval.revision) && approval.availableDecisions.some(decision => decision === "accept" || decision === "decline"))
    .map(approval => approval.approvalId) : []);
  let state: AssistantDispatchTaskState = "unknown";
  if (active) state = pending.size || nativeStatus === "awaiting_approval" ? "waiting_user" : "running";
  else if (current && nativeStatus === "cancelling") state = "stopping";
  else if (current && nativeStatus && TERMINAL.has(nativeStatus)) {
    state = nativeStatus === "succeeded" ? "awaiting_verification"
      : nativeStatus === "cancelled" ? "stopped" : "failed";
  }
  return {
    // Dispatch identity exists before native admission and survives later binding.
    // Tuple encoding avoids delimiter collisions and cross-project conflation.
    id: JSON.stringify([projectId, "dispatch", row.dispatchId]),
    dispatchId: row.dispatchId, projectId, agentId, nativeTaskId, nativeStatus,
    title: boundedText(row.title, 100),
    resultSummary: bound ? boundedText(row.receipt?.resultSummary, 600) : "",
    shouldPoll: current && row.receipt?.shouldPoll === true && ["running", "stopping", "waiting_user"].includes(state),
    state, sourceAvailable: sourceAvailable && !row.lastError, receiptBound: bound, conflictingObservations: false,
    pendingApprovalCount: pending.size, businessAcceptance: "not_evaluated",
  };
}

function fingerprint(task: AssistantDispatchTask): string {
  return JSON.stringify([task.agentId, task.nativeTaskId, task.nativeStatus, task.state,
    task.sourceAvailable, task.receiptBound, task.pendingApprovalCount, task.title, task.resultSummary, task.shouldPoll]);
}

export function projectAssistantDispatchTasks(
  rows: readonly LauncherAssistantDispatch[], options: { sourceAvailable?: boolean } = {},
): AssistantDispatchTaskFeed {
  const indexed = new Map<string, AssistantDispatchTask>();
  let invalidRecords = 0;
  for (const row of rows) {
    if (!identity(row.dispatchId)) { invalidRecords += 1; continue; }
    const task = projectRow(row, options.sourceAvailable !== false);
    const previous = indexed.get(task.id);
    if (!previous) indexed.set(task.id, task);
    else if (previous.conflictingObservations || fingerprint(previous) !== fingerprint(task)) {
      // The feed has no revision/timestamp ordering contract. Never guess which
      // duplicate observation won, including whether an approval is still live.
      indexed.set(task.id, { ...previous, nativeStatus: null, state: "unknown", sourceAvailable: false, receiptBound: false,
        conflictingObservations: true, pendingApprovalCount: 0, resultSummary: "", shouldPoll: false });
    }
  }
  const tasks = [...indexed.values()];
  const counts = { inProgress: 0, waitingUser: 0, awaitingVerification: 0, failed: 0, stopped: 0, unknown: 0 };
  for (const task of tasks) {
    if (task.state === "running" || task.state === "stopping") counts.inProgress += 1;
    else if (task.state === "waiting_user") counts.waitingUser += 1;
    else if (task.state === "awaiting_verification") counts.awaitingVerification += 1;
    else if (task.state === "failed") counts.failed += 1;
    else if (task.state === "stopped") counts.stopped += 1;
    else counts.unknown += 1;
  }
  return { tasks, coverage: "bounded_dispatches", complete: false,
    sourceAvailable: options.sourceAvailable !== false, invalidRecords, counts };
}
