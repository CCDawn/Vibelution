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
  const match = /(?:^|-)message-(\d+)(?:$|-)/.exec(message.id);
  if (!match) {
    return undefined;
  }
  const parsed = Number(match[1]);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function messageSequenceOrder(message: ConversationMessage) {
  return metadataNumber(message, "messageIndex")
    ?? metadataNumber(message, "seq")
    ?? idMessageIndex(message)
    ?? Number.POSITIVE_INFINITY;
}

export function chronologicalConversationMessages(messages: ConversationMessage[]) {
  return messages
    .map((message, index) => ({
      index,
      message,
      sequenceOrder: messageSequenceOrder(message),
      timestampOrder: timestampOrder(message.timestamp),
    }))
    .sort((left, right) =>
      left.timestampOrder - right.timestampOrder
      || left.sequenceOrder - right.sequenceOrder
      || left.index - right.index
    )
    .map((item) => item.message);
}
