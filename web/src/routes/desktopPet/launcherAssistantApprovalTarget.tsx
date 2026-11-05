import { createContext, useContext } from "react";
import type { LauncherAssistantDispatch, LauncherDispatchApproval } from "../../api/launcherAssistant";

/** Ephemeral Launcher navigation intent. Native receipts and approval previews
 * remain authoritative; this target grants no authorization and is not persisted. */
export type LauncherApprovalTarget = {
  nonce: string;
  assistantAgentId: string;
  sessionId: string;
  projectId: string;
  dispatchId: string;
  nativeTaskId: string;
  agentId: string;
  approvalId: string;
};
type SelectedApproval = { row: LauncherAssistantDispatch; request: LauncherDispatchApproval };
export const LauncherApprovalTargetContext = createContext<{
  target: LauncherApprovalTarget | null;
  dismiss: (nonce: string) => void;
} | null>(null);
export function useLauncherApprovalTarget() { return useContext(LauncherApprovalTargetContext); }

export function pendingLauncherDispatchApprovals(rows: readonly LauncherAssistantDispatch[]): SelectedApproval[] {
  return rows.flatMap(row => row.nativeTaskId && row.agentId && !row.lastError && row.receipt?.taskId === row.nativeTaskId
    ? (row.receipt.pendingApprovals ?? []).map(request => ({ row, request })) : []);
}

export function createLauncherApprovalTarget(
  task: { projectId: string | null; dispatchId: string; nativeTaskId: string | null; agentId: string | null },
  rows: readonly LauncherAssistantDispatch[], assistantAgentId: string, sessionId: string,
): LauncherApprovalTarget | null {
  const matches = rows.filter(row => row.projectId === task.projectId && row.dispatchId === task.dispatchId
    && row.nativeTaskId === task.nativeTaskId && row.agentId === task.agentId);
  if (matches.length !== 1 || !assistantAgentId || !sessionId) return null;
  const selected = pendingLauncherDispatchApprovals(matches)[0];
  if (!selected?.request.approvalId || !selected.row.projectId) return null;
  return { nonce: crypto.randomUUID(), assistantAgentId, sessionId, projectId: selected.row.projectId,
    dispatchId: selected.row.dispatchId, nativeTaskId: selected.row.nativeTaskId!, agentId: selected.row.agentId!,
    approvalId: selected.request.approvalId };
}

export function resolveLauncherApprovalTarget(
  target: LauncherApprovalTarget, rows: readonly LauncherAssistantDispatch[], assistantAgentId: string, sessionId: string,
): SelectedApproval | undefined {
  if (target.assistantAgentId !== assistantAgentId || target.sessionId !== sessionId) return undefined;
  const matches = pendingLauncherDispatchApprovals(rows).filter(({ row, request }) => row.projectId === target.projectId
    && row.dispatchId === target.dispatchId && row.nativeTaskId === target.nativeTaskId
    && row.agentId === target.agentId && request.approvalId === target.approvalId);
  return matches.length === 1 ? matches[0] : undefined;
}
