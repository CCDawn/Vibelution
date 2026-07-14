import type { AgentMessage } from "../../agent-thread/types";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";

export type AgentMessageTimelineRowIdentity = {
  messageId: string;
  rowKey: string;
  messageKey: string;
  processKey: string;
  answerKey: string;
};

type TimelineItemKeyInput = Pick<AgentMessageTimelineItem, "id" | "kind"> | {
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

function normalizedMessageTurnId(message: AgentMessage) {
  const turnId = message.turnId
    || metadataText(message.metadata, "turnId")
    || metadataText(message.source.metadata, "turnId");
  return turnId.replace(/^live:/, "");
}

function projectedMessageAnchor(message: AgentMessage) {
  const projectedMessageIds = (message.source.metadata ?? message.metadata)?.projectedMessageIds;
  if (Array.isArray(projectedMessageIds)) {
    const firstId = projectedMessageIds.map((item) => String(item).trim()).find(Boolean);
    if (firstId) {
      return firstId;
    }
  }
  return message.source.id || message.id;
}

function activeTurnRenderKey(message: AgentMessage) {
  const kind = metadataText(message.metadata, "kind") || metadataText(message.source.metadata, "kind");
  const renderKey = metadataText(message.metadata, "renderKey") || metadataText(message.source.metadata, "renderKey");
  if (message.role === "assistant" && kind === "session_active_turn_layer" && renderKey) {
    return `assistant-active:${renderKey}`;
  }
  return "";
}

function baseTimelineRowKey(message: AgentMessage) {
  const renderKey = activeTurnRenderKey(message);
  if (renderKey) {
    return renderKey;
  }
  const turnId = normalizedMessageTurnId(message);
  if (message.role === "assistant" && turnId) {
    return `assistant-turn:${turnId}`;
  }
  return `${message.role}-message:${message.id}`;
}

function timelineRowIdentity(message: AgentMessage, rowKey: string): AgentMessageTimelineRowIdentity {
  return {
    messageId: message.id,
    rowKey,
    messageKey: `${rowKey}:message`,
    processKey: `${rowKey}:process`,
    answerKey: `${rowKey}:answer`,
  };
}

export function buildAgentMessageTimelineRowIdentities(
  messages: AgentMessage[],
): AgentMessageTimelineRowIdentity[] {
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

export function agentMessageTimelineItemRowKey(
  row: Pick<AgentMessageTimelineRowIdentity, "processKey">,
  item: TimelineItemKeyInput,
) {
  return `${row.processKey}:item:${item.kind}:${item.id}`;
}
