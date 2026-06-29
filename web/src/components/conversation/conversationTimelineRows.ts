import type { ConversationMessage } from "../../api/types";
import type { ConversationTimelineItem } from "./conversationTimeline";

export type ConversationTimelineRowIdentity = {
  messageId: string;
  rowKey: string;
  messageKey: string;
  processKey: string;
  answerKey: string;
};

type TimelineItemKeyInput = Pick<ConversationTimelineItem, "id" | "kind"> | {
  id: string;
  kind: string;
};

function metadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

function normalizedMessageTurnId(message: ConversationMessage) {
  return metadataText(message.metadata, "turnId").replace(/^live:/, "");
}

function projectedMessageAnchor(message: ConversationMessage) {
  const projectedMessageIds = message.metadata?.projectedMessageIds;
  if (Array.isArray(projectedMessageIds)) {
    const firstId = projectedMessageIds.map((item) => String(item).trim()).find(Boolean);
    if (firstId) {
      return firstId;
    }
  }
  return message.id;
}

function baseTimelineRowKey(message: ConversationMessage) {
  const turnId = normalizedMessageTurnId(message);
  if (message.role === "assistant" && turnId) {
    return `assistant-turn:${turnId}`;
  }
  return `${message.role}-message:${message.id}`;
}

function timelineRowIdentity(message: ConversationMessage, rowKey: string): ConversationTimelineRowIdentity {
  return {
    messageId: message.id,
    rowKey,
    messageKey: `${rowKey}:message`,
    processKey: `${rowKey}:process`,
    answerKey: `${rowKey}:answer`,
  };
}

export function buildConversationTimelineRowIdentities(
  messages: ConversationMessage[],
): ConversationTimelineRowIdentity[] {
  const baseKeys = messages.map(baseTimelineRowKey);
  const counts = new Map<string, number>();
  for (const key of baseKeys) {
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  return messages.map((message, index) => {
    const baseKey = baseKeys[index];
    const rowKey = (counts.get(baseKey) ?? 0) > 1
      ? `${baseKey}:message:${projectedMessageAnchor(message)}`
      : baseKey;
    return timelineRowIdentity(message, rowKey);
  });
}

export function conversationTimelineItemRowKey(
  row: Pick<ConversationTimelineRowIdentity, "processKey">,
  item: TimelineItemKeyInput,
) {
  return `${row.processKey}:item:${item.kind}:${item.id}`;
}
