import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import { answerProjectionContent } from "./conversationInternalStatus";
import { mergeAgentFeedbackEvents } from "../../agent-thread/agentFeedbackEvents";
import {
  conversationMessageMetadataText,
  conversationMessageTurnId,
} from "./conversationMessageIdentity";
import { projectTimelineProcessMessages } from "./timelineMessageProcessProjection";
import {
  buildAgentMessageTimelineRowIdentities,
  type AgentMessageTimelineRowIdentity,
} from "./agentMessageTimelineRows";

export type AgentMessageTimelineProjectionInput = {
  timelineMessages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
};

export type AgentMessageTimelineProjection = {
  messages: ConversationMessage[];
  agentMessages: AgentMessage[];
  streamingMessages: ConversationMessage[];
  rowIdentities: AgentMessageTimelineRowIdentity[];
};

function isSessionLiveOverlayMessage(message: ConversationMessage) {
  return message.role === "assistant"
    && conversationMessageMetadataText(message.metadata, "kind") === "session_live_overlay";
}

function isSessionActiveTurnLayerMessage(message: ConversationMessage) {
  return message.role === "assistant"
    && conversationMessageMetadataText(message.metadata, "kind") === "session_active_turn_layer";
}

function isSameConversationTurn(left: ConversationMessage, right: ConversationMessage) {
  const leftTurnId = conversationMessageTurnId(left);
  return Boolean(leftTurnId) && leftTurnId === conversationMessageTurnId(right);
}

function mergeUniqueProjectionItems<T>(
  semanticKey: (item: T) => string,
  ...itemGroups: Array<T[] | undefined>
) {
  const merged: T[] = [];
  const indexes = new Map<string, number>();
  for (const group of itemGroups) {
    for (const item of group ?? []) {
      const key = semanticKey(item);
      const existingIndex = indexes.get(key);
      if (existingIndex !== undefined) {
        merged[existingIndex] = item;
        continue;
      }
      indexes.set(key, merged.length);
      merged.push(item);
    }
  }
  return merged.length > 0 ? merged : undefined;
}

function projectionItemIdentity(item: unknown) {
  if (!item || typeof item !== "object") {
    return JSON.stringify(item);
  }
  const record = item as Record<string, unknown>;
  const stableFields = [
    "id",
    "kind",
    "name",
    "sequence",
    "tracePath",
    "operationIds",
    "sourceOperationIds",
    "arguments",
    "input",
    "query",
    "path",
    "filename",
    "url",
    "title",
  ];
  const parts = stableFields
    .map((field) => {
      const value = record[field];
      if (Array.isArray(value)) {
        return value.length > 0 ? `${field}:${value.join("|")}` : "";
      }
      if (value && typeof value === "object") {
        return `${field}:${JSON.stringify(value)}`;
      }
      return value === undefined || value === null || value === "" ? "" : `${field}:${String(value)}`;
    })
    .filter(Boolean);
  return parts.length > 0 ? parts.join("::") : JSON.stringify(item);
}

function normalizeMergedText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function mergeConversationText(...values: Array<string | undefined>) {
  const merged: string[] = [];
  const mergedSignals: string[] = [];
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) {
      continue;
    }
    const signal = normalizeMergedText(text);
    if (mergedSignals.some((existing) => existing === signal || existing.includes(signal))) {
      continue;
    }
    const containedIndex = mergedSignals.findIndex((existing) => signal.includes(existing));
    if (containedIndex >= 0) {
      merged[containedIndex] = text;
      mergedSignals[containedIndex] = signal;
      continue;
    }
    merged.push(text);
    mergedSignals.push(signal);
  }
  return merged.join("\n\n");
}

function mergeLiveOverlayIntoActiveTurnMessage(
  liveOverlayMessage: ConversationMessage,
  activeTurnMessage: ConversationMessage,
): ConversationMessage {
  const feedbackEvents = mergeAgentFeedbackEvents(
    liveOverlayMessage.feedbackEvents,
    activeTurnMessage.feedbackEvents,
  );
  return {
    ...liveOverlayMessage,
    ...activeTurnMessage,
    content: activeTurnMessage.content,
    thought: mergeConversationText(liveOverlayMessage.thought, activeTurnMessage.thought) || undefined,
    streamStage: activeTurnMessage.streamStage || liveOverlayMessage.streamStage,
    streaming: activeTurnMessage.streaming ?? liveOverlayMessage.streaming,
    mentalSnapshot: activeTurnMessage.mentalSnapshot ?? liveOverlayMessage.mentalSnapshot,
    feedbackEvents: feedbackEvents.length > 0 ? feedbackEvents : undefined,
    timelineItems: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.timelineItems, activeTurnMessage.timelineItems),
    toolCalls: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.toolCalls, activeTurnMessage.toolCalls),
    attachments: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.attachments, activeTurnMessage.attachments),
    references: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.references, activeTurnMessage.references),
    metadata: {
      ...(liveOverlayMessage.metadata ?? {}),
      ...(activeTurnMessage.metadata ?? {}),
    },
  };
}

function hasCommittedAssistantAnswerForActiveTurn(
  messages: ConversationMessage[],
  activeTurnMessage: ConversationMessage,
) {
  return messages.some((message) => {
    if (
      message.role !== "assistant"
      || isSessionLiveOverlayMessage(message)
      || isSessionActiveTurnLayerMessage(message)
      || !isSameConversationTurn(message, activeTurnMessage)
    ) {
      return false;
    }
    return Boolean(String(answerProjectionContent(message) ?? "").trim());
  });
}

export function projectAgentMessageTimelineMessages({
  timelineMessages,
  activeTurnMessage,
}: AgentMessageTimelineProjectionInput): AgentMessageTimelineProjection {
  const projectedMessages = (() => {
    if (!activeTurnMessage || hasCommittedAssistantAnswerForActiveTurn(timelineMessages, activeTurnMessage)) {
      return projectTimelineProcessMessages(timelineMessages);
    }
    let mergedActiveTurnMessage = activeTurnMessage;
    const dedupedTimelineMessages = timelineMessages.filter((message) => {
      if (isSessionLiveOverlayMessage(message) && isSameConversationTurn(message, activeTurnMessage)) {
        mergedActiveTurnMessage = mergeLiveOverlayIntoActiveTurnMessage(message, mergedActiveTurnMessage);
        return false;
      }
      return true;
    });
    return projectTimelineProcessMessages([...dedupedTimelineMessages, mergedActiveTurnMessage]);
  })();
  const projectedAgentMessages = projectedMessages.map(conversationMessageToAgentMessage);

  return {
    messages: projectedMessages,
    agentMessages: projectedAgentMessages,
    streamingMessages: projectedMessages.filter((message) => message.streaming),
    rowIdentities: buildAgentMessageTimelineRowIdentities(projectedAgentMessages),
  };
}
