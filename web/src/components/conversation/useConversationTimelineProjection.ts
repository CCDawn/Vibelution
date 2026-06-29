import type { ConversationMessage } from "../../api/types";
import { answerProjectionContent } from "./conversationInternalStatus";
import { mergeConversationFeedbackEvents } from "./conversationFeedbackEvents";
import { projectConversationProcessMessages } from "./conversationProcessProjection";
import {
  buildConversationTimelineRowIdentities,
  type ConversationTimelineRowIdentity,
} from "./conversationTimelineRows";

export type ConversationTimelineProjectionInput = {
  timelineMessages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
};

export type ConversationTimelineProjection = {
  messages: ConversationMessage[];
  streamingMessages: ConversationMessage[];
  rowIdentities: ConversationTimelineRowIdentity[];
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

function conversationMessageTurnId(message: ConversationMessage) {
  return metadataText(message.metadata, "turnId").replace(/^live:/, "");
}

function isSessionLiveOverlayMessage(message: ConversationMessage) {
  return message.role === "assistant" && metadataText(message.metadata, "kind") === "session_live_overlay";
}

function isSessionActiveTurnLayerMessage(message: ConversationMessage) {
  return message.role === "assistant" && metadataText(message.metadata, "kind") === "session_active_turn_layer";
}

function isSameConversationTurn(left: ConversationMessage, right: ConversationMessage) {
  const leftTurnId = conversationMessageTurnId(left);
  return Boolean(leftTurnId) && leftTurnId === conversationMessageTurnId(right);
}

function mergeUniqueJsonItems<T>(...itemGroups: Array<T[] | undefined>) {
  const merged: T[] = [];
  const seen = new Set<string>();
  for (const group of itemGroups) {
    for (const item of group ?? []) {
      const key = JSON.stringify(item);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(item);
    }
  }
  return merged.length > 0 ? merged : undefined;
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
  const feedbackEvents = mergeConversationFeedbackEvents(
    liveOverlayMessage.feedbackEvents,
    activeTurnMessage.feedbackEvents,
  );
  return {
    ...liveOverlayMessage,
    ...activeTurnMessage,
    content: mergeConversationText(answerProjectionContent(liveOverlayMessage), activeTurnMessage.content),
    thought: mergeConversationText(liveOverlayMessage.thought, activeTurnMessage.thought) || undefined,
    streamStage: activeTurnMessage.streamStage || liveOverlayMessage.streamStage,
    streaming: activeTurnMessage.streaming ?? liveOverlayMessage.streaming,
    mentalSnapshot: activeTurnMessage.mentalSnapshot ?? liveOverlayMessage.mentalSnapshot,
    feedbackEvents: feedbackEvents.length > 0 ? feedbackEvents : undefined,
    timelineItems: mergeUniqueJsonItems(liveOverlayMessage.timelineItems, activeTurnMessage.timelineItems),
    toolCalls: mergeUniqueJsonItems(liveOverlayMessage.toolCalls, activeTurnMessage.toolCalls),
    attachments: mergeUniqueJsonItems(liveOverlayMessage.attachments, activeTurnMessage.attachments),
    references: mergeUniqueJsonItems(liveOverlayMessage.references, activeTurnMessage.references),
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

export function projectConversationTimelineMessages({
  timelineMessages,
  activeTurnMessage,
}: ConversationTimelineProjectionInput): ConversationTimelineProjection {
  const projectedMessages = (() => {
    if (!activeTurnMessage || hasCommittedAssistantAnswerForActiveTurn(timelineMessages, activeTurnMessage)) {
      return projectConversationProcessMessages(timelineMessages);
    }
    let mergedActiveTurnMessage = activeTurnMessage;
    const dedupedTimelineMessages = timelineMessages.filter((message) => {
      if (isSessionLiveOverlayMessage(message) && isSameConversationTurn(message, activeTurnMessage)) {
        mergedActiveTurnMessage = mergeLiveOverlayIntoActiveTurnMessage(message, mergedActiveTurnMessage);
        return false;
      }
      return true;
    });
    return projectConversationProcessMessages([...dedupedTimelineMessages, mergedActiveTurnMessage]);
  })();

  return {
    messages: projectedMessages,
    streamingMessages: projectedMessages.filter((message) => message.streaming),
    rowIdentities: buildConversationTimelineRowIdentities(projectedMessages),
  };
}
