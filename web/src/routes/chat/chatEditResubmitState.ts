import type { ConversationMessage, SessionDetail } from "../../api/types";

type EditGuard = NonNullable<SessionDetail["editResubmitProtection"]>;
type DetailMerge = (previous: SessionDetail | undefined, next: SessionDetail) => SessionDetail;

export function editMessageIndex(message: ConversationMessage): number {
  const index = Number(message.metadata?.messageIndex ?? /-message-(\d+)$/.exec(message.id)?.[1]);
  return Number.isFinite(index) && index > 0 ? index : Number.POSITIVE_INFINITY;
}

export function editMessageTurnId(message: ConversationMessage): string {
  return String(("turnId" in message ? message.turnId : "") || message.metadata?.turnId || message.metadata?.turn_id || "").trim();
}

export function isEditAcknowledged(detail: SessionDetail | undefined, submissionId: string): boolean {
  return Boolean(detail?.messages?.some((message) => message.role === "user"
    && message.metadata?.clientSubmissionId === submissionId
    && message.metadata?.optimisticUserMessage !== true));
}

function pending(guard: EditGuard | null | undefined): boolean {
  return Boolean(guard && (!guard.phase || guard.phase === "pending"));
}

function seq(detail: SessionDetail | undefined): number {
  return Number(detail?.ledgerSeq) || 0;
}

/** One bounded edit generation lives with the session cache, never in the journal. */
export function supersededEditDelta(
  guard: EditGuard | null | undefined, turnId: string | undefined, ledgerSeq?: number,
): boolean {
  if (!guard || guard.phase === "rolled_back") return false;
  const id = String(turnId || "").trim();
  return Boolean((id && (id === guard.supersededTurnId || guard.supersededTurnIds?.includes(id)))
    || (ledgerSeq && guard.baseLedgerSeq && ledgerSeq <= guard.baseLedgerSeq));
}

function prefix(detail: SessionDetail, guard: EditGuard): ConversationMessage[] {
  const target = detail.messages.findIndex((message) => message.id === guard.targetMessageId);
  if (target >= 0) return detail.messages.slice(0, target);
  return detail.messages.filter((message) => editMessageIndex(message) < (guard.targetMessageIndex ?? 0));
}

function hideTail(detail: SessionDetail, guard: EditGuard, target: ConversationMessage): SessionDetail {
  const messages = [...prefix(detail, guard), target];
  const cutoff = guard.targetMessageIndex;
  return {
    ...detail,
    messages,
    editResubmitProtection: guard,
    messageWindow: detail.messageWindow && cutoff ? {
      ...detail.messageWindow,
      totalMessages: cutoff,
      returnedMessages: messages.length,
      newestMessageIndex: cutoff,
      hasLater: false,
    } : detail.messageWindow,
  };
}

/** Apply the same edit boundary in RQ structural sharing and sticky painting. */
export function mergeEditResubmitDetail(
  previous: SessionDetail | undefined, next: SessionDetail, merge: DetailMerge,
): SessionDetail {
  if (!previous || previous.id !== next.id) return merge(previous, next);
  const incoming = next.editResubmitProtection;
  const current = previous.editResubmitProtection;
  if (incoming?.phase === "rolled_back") {
    // Only the mutation callback creates this directive after checking identity.
    return next;
  }
  const newEdit = incoming && pending(incoming) && (!current || incoming.clientSubmissionId !== current.clientSubmissionId);
  const guard = newEdit ? incoming : current ?? incoming;
  if (!guard || guard.phase === "rolled_back") return merge(previous, next);

  if (newEdit) {
    const target = next.messages.find((message) => message.id === guard.targetMessageId);
    return target ? hideTail(next, guard, target) : next;
  }

  if (!pending(guard)) {
    // Known old snapshots and sequence-less snapshots of the superseded branch
    // cannot overwrite the accepted generation. A newer branch switch is valid.
    const nextSeq = seq(next);
    const floor = Math.max(seq(previous), guard.acceptedLedgerSeq ?? 0);
    if (nextSeq > 0 && nextSeq < floor) return previous;
    const oldTarget = next.messages?.find((message) => message.id === guard.targetMessageId);
    const otherBranch = oldTarget && oldTarget.metadata?.clientSubmissionId !== guard.clientSubmissionId;
    if (otherBranch && nextSeq <= floor) return previous;
    if (otherBranch && nextSeq > floor) return { ...merge(previous, next), editResubmitProtection: undefined };
    if (!nextSeq && next.messages?.some((message) => supersededEditDelta(guard, editMessageTurnId(message)))) {
      return previous;
    }
    return { ...merge(previous, next), editResubmitProtection: guard };
  }

  if (isEditAcknowledged(next, guard.clientSubmissionId)) {
    // Remove the superseded branch before even a non-windowed sticky union.
    const merged = merge({ ...previous, messages: prefix(previous, guard) }, next);
    return {
      ...merged,
      messageWindow: next.messageWindow ?? merged.messageWindow,
      editResubmitProtection: { ...guard, phase: "accepted", acceptedLedgerSeq: seq(next) },
    };
  }

  if (!Array.isArray(next.messages)) return { ...merge(previous, next), editResubmitProtection: guard };
  const target = previous.messages.find((message) => message.id === guard.targetMessageId);
  if (!target) return previous;
  // Old polling/SSE snapshots may contribute earlier pages, never the edited
  // message, stale terminal status, or the superseded tail.
  const history = merge(previous, { ...next, messages: prefix(next, guard) });
  return hideTail({ ...history, ...previous, messages: history.messages }, guard, target);
}

export function rollbackEditResubmit(
  current: SessionDetail | undefined, original: SessionDetail, submissionId: string,
): SessionDetail | undefined {
  const guard = current?.editResubmitProtection;
  if (!guard || !pending(guard) || guard.clientSubmissionId !== submissionId || isEditAcknowledged(current, submissionId)) {
    return current;
  }
  return { ...original, editResubmitProtection: { ...guard, phase: "rolled_back" } };
}
