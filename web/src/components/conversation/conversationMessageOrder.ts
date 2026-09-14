import type { ConversationMessage } from "../../api/types";
import {
  isLiveOverlayMessage,
  isSteerGuidanceMessage,
} from "./conversationMessagePredicates";

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

function messageTurnId(message: ConversationMessage) {
  const metadataTurnId = message.metadata?.turnId;
  if (typeof metadataTurnId === "string" && metadataTurnId.trim()) {
    return metadataTurnId.trim();
  }
  if (message.role === "assistant") {
    return String(message.turnId ?? "").trim();
  }
  return "";
}

function clientSubmissionId(message: ConversationMessage) {
  const value = message.metadata?.clientSubmissionId ?? message.metadata?.client_submission_id;
  return typeof value === "string" ? value.trim() : "";
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
 * Steer guidance that belongs to the turn currently streaming under a live
 * overlay must not jump above that overlay: the operator sent it mid-turn, so
 * it reads naturally right after the in-flight output (Codex-style steer)
 * instead of before the answer it interrupted.
 */
function collectActiveTurnSteerMessages(messages: ConversationMessage[]) {
  const overlayTurnIds = new Set(
    messages
      .filter((message) => isLiveOverlayMessage(message))
      .map((message) => messageTurnId(message))
      .filter(Boolean),
  );
  const activeSteer = new Set<ConversationMessage>();
  if (overlayTurnIds.size === 0) {
    return activeSteer;
  }
  for (const message of messages) {
    if (
      isSteerGuidanceMessage(message)
      && overlayTurnIds.has(messageTurnId(message))
    ) {
      activeSteer.add(message);
    }
  }
  return activeSteer;
}

function deferActiveTurnSteerMessages(
  messages: ConversationMessage[],
  deferred: Set<ConversationMessage>,
) {
  const rest = messages.filter((message) => !deferred.has(message));
  let insertAt = rest.length;
  for (let index = rest.length - 1; index >= 0; index -= 1) {
    if (isLiveOverlayMessage(rest[index])) {
      insertAt = index + 1;
      break;
    }
  }
  return [
    ...rest.slice(0, insertAt),
    ...messages.filter((message) => deferred.has(message)),
    ...rest.slice(insertAt),
  ];
}

/**
 * Order messages for the conversation timeline.
 *
 * Primary key is journal sequence (messageIndex / seq / id), matching backend
 * transcript chain and Codex-style turn order. Wall-clock timestamps are only
 * a tie-breaker between messages that share a journal sequence; messages
 * without any sequence keep their input (append) order — sorting them by
 * timestamp is wrong because optimistic user messages carry the client clock
 * while live assistant layers carry the server clock, so a small skew swaps
 * their order.
 *
 * Mid-turn steer guidance for the streaming turn is the one exception: it is
 * demoted to the unsequenced group and appended after that turn's live overlay
 * so the operator's guidance renders after the in-flight output it steered,
 * matching the Codex keyboard behavior. Once the turn settles the overlay
 * disappears and journal order applies again.
 */
export function chronologicalConversationMessages(messages: ConversationMessage[]) {
  const deferredSteer = collectActiveTurnSteerMessages(messages);
  const inputOrder = deferredSteer.size > 0
    ? deferActiveTurnSteerMessages(messages, deferredSteer)
    : messages;
  return inputOrder
    .map((message, index) => ({
      index,
      message,
      sequenceOrder: deferredSteer.has(message)
        ? Number.POSITIVE_INFINITY
        : messageSequenceOrder(message),
      timestampOrder: timestampOrder(message.timestamp),
      clientSubmissionId: clientSubmissionId(message),
    }))
    .sort((left, right) => {
      if (
        left.clientSubmissionId
        && left.clientSubmissionId === right.clientSubmissionId
        && left.message.role !== right.message.role
      ) {
        return left.message.role === "user" ? -1 : 1;
      }
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
      // Both lack a journal sequence. The input order is already the append
      // order (canonical timeline plus the active turn layer appended last).
      // Sorting by wall-clock here is wrong: optimistic user messages carry a
      // client clock timestamp while live assistant layers carry the server
      // clock, so a small skew swaps them. Keep the stable input order.
      return left.index - right.index;
    })
    .map((item) => item.message);
}
