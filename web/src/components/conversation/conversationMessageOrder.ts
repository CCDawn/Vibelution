import type { ConversationMessage } from "../../api/types";

function timestampOrder(value: string) {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.POSITIVE_INFINITY;
}

function metadataNumber(message: ConversationMessage, key: string) {
  const value = message.metadata?.[key];
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function idMessageIndex(message: ConversationMessage) {
  // Prefer trailing -message-N (session journal ids), then any -message-N segment.
  const trailing = /-message-(\d+)$/.exec(message.id);
  const match = trailing ?? /(?:^|-)message-(\d+)(?:$|-)/.exec(message.id);
  if (!match) {
    return undefined;
  }
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : undefined;
}

/**
 * Journal sequence for a conversation message.
 * Prefer explicit metadata, then id-encoded message index (Codex/session journal order).
 */
export function messageSequenceOrder(message: ConversationMessage) {
  return metadataNumber(message, "messageIndex")
    ?? metadataNumber(message, "seq")
    ?? idMessageIndex(message)
    ?? Number.POSITIVE_INFINITY;
}

function hasFiniteSequence(order: number) {
  return Number.isFinite(order) && order !== Number.POSITIVE_INFINITY;
}

/**
 * Order messages for the conversation timeline.
 *
 * Primary key is journal sequence (messageIndex / seq / id), matching backend
 * transcript chain and Codex-style turn order. Wall-clock timestamps are only a
 * fallback when sequence is missing — timestamp-first reordering was scrambling
 * turns after frontend unification when clocks or sticky merges disagreed.
 */
export function chronologicalConversationMessages(messages: ConversationMessage[]) {
  return messages
    .map((message, index) => ({
      index,
      message,
      sequenceOrder: messageSequenceOrder(message),
      timestampOrder: timestampOrder(message.timestamp),
    }))
    .sort((left, right) => {
      const leftHasSeq = hasFiniteSequence(left.sequenceOrder);
      const rightHasSeq = hasFiniteSequence(right.sequenceOrder);
      if (leftHasSeq && rightHasSeq) {
        return left.sequenceOrder - right.sequenceOrder
          || left.timestampOrder - right.timestampOrder
          || left.index - right.index;
      }
      if (leftHasSeq !== rightHasSeq) {
        // Prefer journal-keyed messages over unsequenced noise in the same batch.
        return leftHasSeq ? -1 : 1;
      }
      return left.timestampOrder - right.timestampOrder
        || left.index - right.index;
    })
    .map((item) => item.message);
}
