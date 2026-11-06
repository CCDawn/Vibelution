import type { QueryClient, QueryKey } from "@tanstack/react-query";
import type { SessionDetail, SessionQueuedTurn, SessionReferenceAttachment } from "../../api/types";
import {
  appendOptimisticUserMessage, markOptimisticUserMessageAccepted, markSessionDetailRunning,
  mergeSessionDetailMessageWindow, removeOptimisticUserMessage, removeSettledOptimisticUserMessages, type OptimisticUserMessageInput,
} from "../chatSessionState";
import { sessionReferenceId } from "./chatComposerSubmitModel";

/** Cache-only receipt annotation. The ACK proves queue acceptance, but this
 * local paint is not evidence that an authoritative queue read has seen it. */
export function isLocalQueuedSubmit(row: SessionQueuedTurn) {
  return (row as SessionQueuedTurn & { localSubmissionReceipt?: boolean }).localSubmissionReceipt === true;
}

/** Transport-independent paint only. A local row never proves native admission. */
export function beginSessionSubmit(detail: SessionDetail | undefined, input: OptimisticUserMessageInput, queued = false) {
  return queued ? detail : markSessionDetailRunning(appendOptimisticUserMessage(detail, input));
}

export function acceptSessionSubmit(
  detail: SessionDetail | undefined, input: OptimisticUserMessageInput,
  receipt: { turnId: string; queued?: boolean; queuedTurnId?: string; queuePosition?: number; queuedAt?: string; acceptedAt?: string },
) {
  if (!detail) return detail;
  if (!receipt.queued && !receipt.queuedTurnId) return markOptimisticUserMessageAccepted(detail, input, receipt.turnId);
  const next = Array.isArray(detail.messages) ? removeOptimisticUserMessage(detail, input)! : detail;
  const rows = next.queuedTurns ?? [];
  if (!receipt.queuedTurnId || rows.some(row => row.id === receipt.queuedTurnId || row.clientSubmissionId === input.clientSubmissionId)) return next;
  const at = receipt.queuedAt || receipt.acceptedAt || input.createdAt || new Date().toISOString();
  return { ...next, queuedTurns: [...rows, { id: receipt.queuedTurnId,
    position: receipt.queuePosition ?? rows.length + 1, status: "queued", content: input.content,
    clientSubmissionId: input.clientSubmissionId, createdAt: at, updatedAt: at,
    localSubmissionReceipt: true, attachments: input.attachments, references: input.references }] };
}

/** Some small hosts/tests omit messageWindow. Preserve uncommitted user paint
 * across those reads too; native submission matching owns replacement/dedupe. */
export function mergeSessionSubmitDetail(previous: SessionDetail | undefined, next: SessionDetail): SessionDetail {
  let merged = mergeSessionDetailMessageWindow(previous, next);
  if (previous?.id !== next.id) return merged;
  for (const message of previous.messages ?? []) {
    if (message.role !== "user" || message.metadata?.optimisticUserMessage !== true) continue;
    const requestId = String(message.metadata.clientSubmissionId || "");
    if (!requestId || next.queuedTurns?.some(row => row.clientSubmissionId === requestId)) continue;
    const input = { sessionId: next.id, clientSubmissionId: requestId, content: message.content,
      attachments: message.attachments, references: message.references, createdAt: message.timestamp };
    merged = appendOptimisticUserMessage(merged, input)!;
    const turnId = String(message.metadata.turnId || "");
    if (turnId) merged = markOptimisticUserMessageAccepted(merged, input, turnId)!;
  }
  const messages = removeSettledOptimisticUserMessages(merged.messages);
  if (messages !== merged.messages) merged = { ...merged, messages };
  for (const row of previous.queuedTurns ?? []) {
    if (!isLocalQueuedSubmit(row) || !row.clientSubmissionId) continue;
    const requestId = row.clientSubmissionId;
    const admitted = (Array.isArray(next.messages) ? next.messages : []).some(message => message.role === "user" && message.metadata?.optimisticUserMessage !== true
      && message.metadata?.clientSubmissionId === requestId) || next.activeTask?.metadata?.clientSubmissionId === requestId;
    if (admitted || merged.queuedTurns?.some(candidate => candidate.id === row.id || candidate.clientSubmissionId === requestId)) continue;
    merged = { ...merged, queuedTurns: [...(merged.queuedTurns ?? []), row] };
  }
  return merged;
}

/** Deliberate removals bypass the window UNION structuralSharing policy. */
export function removeSessionSubmitPaint(client: QueryClient, queryKey: QueryKey, input: OptimisticUserMessageInput,
  rollback?: { previous: SessionDetail | undefined; optimistic: SessionDetail | undefined }) {
  const query = client.getQueryCache().find<SessionDetail>({ queryKey, exact: true });
  if (!Array.isArray(query?.state.data?.messages)) return;
  let next = removeOptimisticUserMessage(query.state.data, input);
  if (next && rollback?.previous && query.state.data === rollback.optimistic) {
    next = { ...next, status: rollback.previous.status, currentPhase: rollback.previous.currentPhase,
      lastTurnError: rollback.previous.lastTurnError };
  }
  if (next !== query.state.data) query.setState({ data: next, dataUpdatedAt: Date.now() });
}

export function sameSubmittedReferenceSnapshot(current: SessionReferenceAttachment, submitted: SessionReferenceAttachment): boolean {
  if (sessionReferenceId(current) !== sessionReferenceId(submitted)) return false;
  if (current.kind === "message" || submitted.kind === "message") {
    return current.kind === submitted.kind && current.sourceSessionId === submitted.sourceSessionId
      && current.sourceMessageId === submitted.sourceMessageId && current.quote === submitted.quote;
  }
  return true;
}
