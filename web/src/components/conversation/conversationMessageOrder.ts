import type { ConversationMessage } from "../../api/types";
import { isLiveOverlayMessage } from "./conversationMessagePredicates";

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

const UNSEQUENCED_ORDER_BASE = 1e9;

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
 * Rows without a journal sequence park after every sequenced row while keeping
 * their append order, so one sequence axis decides every comparison. Comparing
 * "has a sequence" against "matches position N" let a durable row jump any
 * unsequenced neighbour, which reordered freshly sent user messages as soon as
 * a detail refresh replaced the optimistic row with the journal row.
 */
function sequencedOrderOrTail(order: number, index: number) {
  return hasFiniteSequence(order) ? order : UNSEQUENCED_ORDER_BASE + index;
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
 * Received steer guidance keeps its journal sequence. The growing live answer
 * stays at the tail, where the timeline can follow it without a static guidance
 * row below it moving that answer into virtualized history.
 */
export function chronologicalConversationMessages(messages: ConversationMessage[]) {
  return messages
    .map((message, index) => ({
      index,
      message,
      // Folding durable segments into an overlay can leave an old messageIndex
      // on its metadata. It still represents the growing tail, not that segment.
      sequenceOrder: isLiveOverlayMessage(message)
        ? Number.POSITIVE_INFINITY
        : sequencedOrderOrTail(messageSequenceOrder(message), index),
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
      return left.sequenceOrder - right.sequenceOrder
        || left.timestampOrder - right.timestampOrder
        || left.index - right.index;
    })
    .map((item) => item.message);
}
