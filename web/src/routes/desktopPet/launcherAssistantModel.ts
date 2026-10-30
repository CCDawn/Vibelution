import type { LauncherAssistantDispatch } from "../../api/launcherAssistant";
import type { PetActivityTone, PetAnimationState } from "../../api/types/petActivity";
import type { SessionDetail, SessionQueuedTurn } from "../../api/types";
import { exactAcceptedSubmitTurnId, findSubmitAcceptanceEvidence } from "../chat/chatSubmitAcceptanceReadback";
import { hasExecutionOwnership, resolveSessionActivity, type SessionActivitySource } from "../sessionActivityState";

export type LauncherAssistantSubmission = { message: string; requestId: string; draftSnapshot?: string; attachmentIds?: string[]; attachmentSnapshotIds?: string[] };
export type LauncherAssistantQueuedAcceptance = { id: string; clientSubmissionId: string; observed: boolean };
type LauncherAssistantActivitySource = SessionActivitySource & Partial<Pick<SessionDetail, "messages" | "activeTask">>
  & { queuedTurns?: Array<Pick<SessionQueuedTurn, "id" | "status" | "clientSubmissionId">> };

/** Read-only recovery of the original request; queue IDs are never Turn IDs. */
export function launcherAssistantRequestReadback(source: LauncherAssistantActivitySource | undefined, requestId: string): {
  turnId: string; queuedAcceptance: LauncherAssistantQueuedAcceptance | null;
} | null {
  if (!source || !requestId) return null;
  const detail = source as SessionDetail;
  const evidence = findSubmitAcceptanceEvidence(detail, requestId);
  const turnId = evidence ? exactAcceptedSubmitTurnId(detail, requestId, evidence) : "";
  if (turnId) return { turnId, queuedAcceptance: null };
  const queued = source.queuedTurns?.find(row => row.clientSubmissionId === requestId && row.id.trim());
  return queued ? { turnId: "", queuedAcceptance: { id: queued.id, clientSubmissionId: requestId, observed: true } } : null;
}

/** Queue IDs identify native rows, never native Turns. Correlate admission by submission ID. */
export function launcherAssistantQueueReadback(
  source: Pick<SessionDetail, "queuedTurns" | "messages" | "activeTask"> | undefined,
  receipt: LauncherAssistantQueuedAcceptance | null,
): { receipt: LauncherAssistantQueuedAcceptance | null; admittedTurnId: string; removed: boolean } {
  if (!source || !receipt) return { receipt, admittedTurnId: "", removed: false };
  const row = source.queuedTurns?.find(item => item.id === receipt.id && item.clientSubmissionId === receipt.clientSubmissionId);
  if (row) return { receipt: receipt.observed ? receipt : { ...receipt, observed: true }, admittedTurnId: "", removed: false };
  const detail = source as SessionDetail;
  const evidence = findSubmitAcceptanceEvidence(detail, receipt.clientSubmissionId);
  const admittedTurnId = evidence ? exactAcceptedSubmitTurnId(detail, receipt.clientSubmissionId, evidence) : "";
  if (admittedTurnId) return { receipt: null, admittedTurnId, removed: false };
  // A vanished observed row is a removal, not success. Never infer admission from time/status.
  return { receipt, admittedTurnId: "", removed: receipt.observed };
}

export function launcherAssistantQueueLabel(status: string, lang: "zh" | "en"): string {
  const labels: Record<string, readonly [string, string]> = {
    queued: ["已排队", "Queued"], starting: ["排队消息正在入场", "Queued message starting"],
    paused: ["排队消息已暂停", "Queued message paused"], blocked: ["排队消息需要处理", "Queued message blocked"],
  };
  return labels[status]?.[lang === "zh" ? 0 : 1] || `${lang === "zh" ? "原生队列状态" : "Native queue status"}: ${status}`;
}

/** An unconfirmed send is retried verbatim, even if a caller supplies a new draft. */
export function launcherAssistantSubmission(
  outstanding: LauncherAssistantSubmission | null,
  draft: string,
  createId: () => string = () => crypto.randomUUID(),
  attachmentIds: string[] = [],
  attachmentSnapshotIds: string[] = [],
): LauncherAssistantSubmission | null {
  if (outstanding) return outstanding;
  const message = draft.trim();
  if (!message && !attachmentIds.length) return null;
  return attachmentIds.length ? { message, requestId: createId(), draftSnapshot: draft, attachmentIds, attachmentSnapshotIds }
    : { message, requestId: createId(), draftSnapshot: draft };
}

export function launcherAssistantActivity(source: SessionActivitySource = {}): {
  tone: PetActivityTone; animationState: PetAnimationState;
} {
  const state = resolveSessionActivity(source);
  if (state.outcome === "failed") return { tone: "error", animationState: "alert" };
  if (state.execution === "paused") return { tone: "approval", animationState: "waiting" };
  if (hasExecutionOwnership(state.execution)) return { tone: "running", animationState: "thinking" };
  // Resting/ready says nothing about whether the user's goal was achieved.
  return { tone: "idle", animationState: "idle" };
}

export function launcherAssistantPollInterval(visible: boolean, source?: LauncherAssistantActivitySource, acceptedTurnId?: string, queuedAcceptance?: LauncherAssistantQueuedAcceptance | null, pendingRequestIds: readonly string[] = []): number | false {
  if (!visible) return false;
  for (const requestId of pendingRequestIds) {
    const recovered = launcherAssistantRequestReadback(source, requestId);
    if (!recovered || (recovered.turnId && source?.activeTurnId !== recovered.turnId && source?.lastTurnTerminalTurnId !== recovered.turnId)) return 2_000;
  }
  if (queuedAcceptance && !queuedAcceptance.observed) return 2_000;
  if (source?.queuedTurns?.some(row => row.status === "queued" || row.status === "starting")) return 2_000;
  // Acceptance precedes the detail projection. A stale ready/previous terminal
  // must not retire the newly accepted Turn before it becomes authoritative.
  if (acceptedTurnId && source?.activeTurnId !== acceptedTurnId && source?.lastTurnTerminalTurnId !== acceptedTurnId) return 2_000;
  if (!source || hasExecutionOwnership(resolveSessionActivity(source).execution)) return 2_000;
  return false;
}

/** Receipt status belongs to the native task; do not project it as business acceptance. */
export function launcherDispatchLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) return lang === "zh" ? "回执暂不可用" : "Receipt unavailable";
  const status = row.receipt?.status;
  return status ? `${lang === "zh" ? "原生任务状态" : "Native task status"}: ${status}`
    : lang === "zh" ? "等待原生任务回执" : "Waiting for native task receipt";
}

/** Humanized receipt lead for the embedded page rows. Same branch shape as
 * launcherDispatchLabel (error → unavailable, known enum → word, else
 * waiting), but terminal native statuses read as plain words and an unknown
 * enum keeps the raw fallback instead of pretending success. The floating
 * window keeps launcherDispatchLabel untouched. */
export function launcherDispatchReceiptLabel(row: LauncherAssistantDispatch, lang: "zh" | "en"): string {
  if (row.lastError) return lang === "zh" ? "回执暂不可用" : "Receipt unavailable";
  const status = row.receipt?.status;
  const words: Record<string, readonly [string, string]> = {
    succeeded: ["成功", "Succeeded"], failed: ["失败", "Failed"],
    cancelled: ["已取消", "Cancelled"], timed_out: ["已超时", "Timed out"],
  };
  if (status && words[status]) return words[status][lang === "zh" ? 0 : 1];
  return status ? `${lang === "zh" ? "原生任务状态" : "Native task status"}: ${status}`
    : lang === "zh" ? "待回执" : "Awaiting receipt";
}
