import type { ConversationMessage, ConversationTimelineItem } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import { answerProjectionContent } from "./conversationInternalStatus";
import { mergeAgentFeedbackEvents } from "../../agent-thread/agentFeedbackEvents";
import {
  shouldDisplayRuntimeStatus,
  shouldDisplayTranscriptCell,
} from "./conversationDisplayProtocol";
import {
  conversationMessageMetadataText,
  conversationMessageTurnId,
  projectedConversationMessageIdsOrSelf,
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

type ConversationFeedbackEvent = NonNullable<ConversationMessage["feedbackEvents"]>[number];

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

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function hasVisibleFeedbackEvent(event: ConversationFeedbackEvent) {
  if (!shouldDisplayRuntimeStatus({
    kind: event.kind,
    name: event.name,
    status: event.status,
    summary: event.summary,
    resultPreview: event.resultPreview,
    error: event.error,
    failureClass: event.failureClass,
    timedOut: event.timedOut,
  })) {
    return false;
  }
  if (event.kind === "status") {
    return true;
  }
  return Boolean(
    compactText(event.name)
    || compactText(event.summary)
    || compactText(event.resultPreview)
    || compactText(event.error)
    || compactText(event.failureClass)
  );
}

function visibleFeedbackEvents(events: ConversationFeedbackEvent[] | undefined) {
  const visible = (events ?? []).filter(hasVisibleFeedbackEvent);
  return visible.length > 0 ? visible : undefined;
}

function hasVisibleTimelineItem(item: ConversationTimelineItem) {
  if (item.kind === "status") {
    return shouldDisplayRuntimeStatus({
      kind: "status",
      name: item.title,
      status: item.status,
      summary: item.summary,
      resultPreview: item.preview ?? item.text,
      text: item.text,
    });
  }
  if (item.kind === "assistant_text" || item.kind === "thought") {
    return Boolean(compactText(item.text) || compactText(item.summary) || compactText(item.preview));
  }
  return Boolean(
    compactText(item.title)
    || compactText(item.summary)
    || compactText(item.text)
    || compactText(item.preview)
    || (item.operationIds?.length ?? 0) > 0
    || (item.sourceOperationIds?.length ?? 0) > 0
  );
}

function hasVisibleCodexTranscript(message: ConversationMessage) {
  const transcript = message.codexTranscript;
  return Boolean(
    transcript
    && String(transcript.source ?? "").trim() === "native"
    && Array.isArray(transcript.cells)
    && transcript.cells.some(shouldDisplayTranscriptCell)
  );
}

function hasVisibleMentalSnapshot(message: ConversationMessage) {
  const snapshot = message.mentalSnapshot;
  return Boolean(
    snapshot
    && [
      snapshot.mood,
      snapshot.feeling,
      snapshot.whisper,
      snapshot.summary,
      snapshot.cognitiveState,
      snapshot.intervention,
    ].some(compactText)
  );
}

function hasVisibleProjectionMessageContent(message: ConversationMessage) {
  return Boolean(
    compactText(answerProjectionContent(message))
    || compactText(message.thought)
    || hasVisibleMentalSnapshot(message)
    || visibleFeedbackEvents(message.feedbackEvents)?.length
    || (message.toolCalls?.length ?? 0) > 0
    || (message.timelineItems ?? []).some(hasVisibleTimelineItem)
    || hasVisibleCodexTranscript(message)
    || (message.attachments?.length ?? 0) > 0
    || (message.references?.length ?? 0) > 0
  );
}

function mergeProjectedMessageIds(...messages: ConversationMessage[]) {
  const ids: string[] = [];
  const seen = new Set<string>();
  for (const message of messages) {
    for (const id of projectedConversationMessageIdsOrSelf(message)) {
      if (seen.has(id)) {
        continue;
      }
      seen.add(id);
      ids.push(id);
    }
  }
  return ids;
}

function mergeLiveOverlayIntoActiveTurnMessage(
  liveOverlayMessage: ConversationMessage,
  activeTurnMessage: ConversationMessage,
): ConversationMessage {
  const feedbackEvents = visibleFeedbackEvents(mergeAgentFeedbackEvents(
    liveOverlayMessage.feedbackEvents,
    activeTurnMessage.feedbackEvents,
  ));
  return {
    ...liveOverlayMessage,
    ...activeTurnMessage,
    content: activeTurnMessage.content,
    thought: mergeConversationText(liveOverlayMessage.thought, activeTurnMessage.thought) || undefined,
    streamStage: activeTurnMessage.streamStage || liveOverlayMessage.streamStage,
    streaming: activeTurnMessage.streaming ?? liveOverlayMessage.streaming,
    mentalSnapshot: activeTurnMessage.mentalSnapshot ?? liveOverlayMessage.mentalSnapshot,
    feedbackEvents,
    timelineItems: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.timelineItems, activeTurnMessage.timelineItems),
    toolCalls: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.toolCalls, activeTurnMessage.toolCalls),
    attachments: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.attachments, activeTurnMessage.attachments),
    references: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.references, activeTurnMessage.references),
    metadata: {
      ...(liveOverlayMessage.metadata ?? {}),
      ...(activeTurnMessage.metadata ?? {}),
      projectedMessageIds: mergeProjectedMessageIds(liveOverlayMessage, activeTurnMessage),
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
    const visibleTimelineMessages = timelineMessages.filter(hasVisibleProjectionMessageContent);
    if (!activeTurnMessage || hasCommittedAssistantAnswerForActiveTurn(visibleTimelineMessages, activeTurnMessage)) {
      return projectTimelineProcessMessages(visibleTimelineMessages);
    }
    let mergedActiveTurnMessage = activeTurnMessage;
    const dedupedTimelineMessages = visibleTimelineMessages.filter((message) => {
      if (isSessionLiveOverlayMessage(message) && isSameConversationTurn(message, activeTurnMessage)) {
        mergedActiveTurnMessage = mergeLiveOverlayIntoActiveTurnMessage(message, mergedActiveTurnMessage);
        return false;
      }
      return true;
    });
    if (!hasVisibleProjectionMessageContent(mergedActiveTurnMessage)) {
      return projectTimelineProcessMessages(dedupedTimelineMessages);
    }
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
