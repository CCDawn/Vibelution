import type { ConversationMessage, ConversationTimelineItem } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import { answerProjectionContent } from "./conversationInternalStatus";
import { mergeAgentFeedbackEvents } from "../../agent-thread/agentFeedbackEvents";
import {
  shouldDisplayRuntimeStatus,
  shouldDisplayTranscriptCell,
} from "./conversationDisplayProtocol";
import { isTurnErrorMessage } from "./conversationMessagePredicates";
import {
  conversationMessageMetadataText,
  conversationMessageTurnId,
  projectedConversationMessageIdsOrSelf,
} from "./conversationMessageIdentity";
import { chronologicalConversationMessages } from "./conversationMessageOrder";
import {
  mergeCodexTranscripts,
  projectTimelineProcessMessages,
} from "./timelineMessageProcessProjection";
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

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function repeatedPersistedMessageKey(message: ConversationMessage) {
  const turnId = conversationMessageTurnId(message);
  if (
    !turnId
    || message.streaming
    || isSessionLiveOverlayMessage(message)
    || isSessionActiveTurnLayerMessage(message)
  ) {
    return "";
  }
  const hasSemanticPayload = Boolean(
    message.role === "user"
    || compactText(message.content)
    || compactText(message.thought)
    || (message.toolCalls?.length ?? 0) > 0
    || (message.feedbackEvents?.length ?? 0) > 0
    || (message.attachments?.length ?? 0) > 0
    || (message.references?.length ?? 0) > 0
  );
  if (!hasSemanticPayload) {
    return "";
  }
  return JSON.stringify({
    role: message.role,
    turnId,
    kind: conversationMessageMetadataText(message.metadata, "kind"),
    timestamp: message.timestamp,
    content: message.content,
    thought: message.thought,
    mentalSnapshot: message.mentalSnapshot,
    streamStage: message.streamStage,
    toolCalls: message.toolCalls ?? [],
    feedbackEvents: message.feedbackEvents ?? [],
    attachments: message.attachments ?? [],
    references: message.references ?? [],
  });
}

function consolidateRepeatedPersistedMessages(messages: ConversationMessage[]) {
  const consolidated: ConversationMessage[] = [];
  const indexes = new Map<string, number>();
  for (const message of messages) {
    const key = repeatedPersistedMessageKey(message);
    const existingIndex = key ? indexes.get(key) : undefined;
    if (existingIndex === undefined) {
      if (key) {
        indexes.set(key, consolidated.length);
      }
      consolidated.push(message);
      continue;
    }
    const existing = consolidated[existingIndex];
    consolidated[existingIndex] = {
      ...existing,
      metadata: {
        ...(existing.metadata ?? {}),
        projectedMessageIds: mergeProjectedMessageIds(existing, message),
      },
    };
  }
  return consolidated;
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

function withoutShadowedTerminalFailureStatuses(messages: ConversationMessage[]) {
  const terminalErrorTurnIds = new Set(
    messages
      .filter(isTurnErrorMessage)
      .map(conversationMessageTurnId)
      .filter(Boolean),
  );
  if (terminalErrorTurnIds.size === 0) {
    return messages;
  }
  return messages.map((message) => {
    const turnId = conversationMessageTurnId(message);
    if (
      message.role !== "assistant"
      || isTurnErrorMessage(message)
      || !turnId
      || !terminalErrorTurnIds.has(turnId)
    ) {
      return message;
    }
    const feedbackEvents = message.feedbackEvents?.filter((event) => !(
      event.kind === "status" && event.status === "failed"
    ));
    if ((feedbackEvents?.length ?? 0) === (message.feedbackEvents?.length ?? 0)) {
      return message;
    }
    return {
      ...message,
      feedbackEvents: feedbackEvents?.length ? feedbackEvents : undefined,
    };
  });
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

function hasVisibleProjectionMessageContent(message: ConversationMessage) {
  return Boolean(
    compactText(answerProjectionContent(message))
    || visibleFeedbackEvents(message.feedbackEvents)?.length
    || (message.timelineItems ?? []).some(hasVisibleTimelineItem)
    || hasVisibleCodexTranscript(message)
    || (message.attachments?.length ?? 0) > 0
    || (message.references?.length ?? 0) > 0
  );
}

function shouldKeepStreamingActiveTurnPlaceholder(message: ConversationMessage) {
  return Boolean(
    message.role === "assistant"
    && message.streaming
    && isSessionActiveTurnLayerMessage(message)
  );
}

function compactStreamingActiveTurnPlaceholderMessage(message: ConversationMessage): ConversationMessage {
  return {
    ...message,
    content: answerProjectionContent(message),
    thought: compactText(message.thought) ? message.thought : undefined,
    mentalSnapshot: undefined,
    feedbackEvents: visibleFeedbackEvents(message.feedbackEvents),
    toolCalls: undefined,
  };
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
    thought: compactText(activeTurnMessage.thought) ? activeTurnMessage.thought : undefined,
    streamStage: activeTurnMessage.streamStage || liveOverlayMessage.streamStage,
    streaming: activeTurnMessage.streaming ?? liveOverlayMessage.streaming,
    mentalSnapshot: undefined,
    feedbackEvents,
    timelineItems: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.timelineItems, activeTurnMessage.timelineItems),
    toolCalls: undefined,
    attachments: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.attachments, activeTurnMessage.attachments),
    references: mergeUniqueProjectionItems(projectionItemIdentity, liveOverlayMessage.references, activeTurnMessage.references),
    codexTranscript: mergeCodexTranscripts(
      liveOverlayMessage.codexTranscript,
      activeTurnMessage.codexTranscript,
      activeTurnMessage.id,
    ),
    turnItems: consolidateSessionTurnItemsV2(
      liveOverlayMessage.turnItems,
      activeTurnMessage.turnItems,
    ),
    metadata: {
      ...(liveOverlayMessage.metadata ?? {}),
      ...(activeTurnMessage.metadata ?? {}),
      projectedMessageIds: mergeProjectedMessageIds(liveOverlayMessage, activeTurnMessage),
    },
  };
}

function committedAssistantAnswerForTurn(
  messages: ConversationMessage[],
  turnMessage: ConversationMessage,
) {
  return messages.find((message) => {
    if (
      message.role !== "assistant"
      || isSessionLiveOverlayMessage(message)
      || isSessionActiveTurnLayerMessage(message)
      || !isSameConversationTurn(message, turnMessage)
    ) {
      return false;
    }
    return Boolean(String(answerProjectionContent(message) ?? "").trim());
  });
}

function hasCommittedAssistantAnswerForActiveTurn(
  messages: ConversationMessage[],
  activeTurnMessage: ConversationMessage,
) {
  return Boolean(committedAssistantAnswerForTurn(messages, activeTurnMessage));
}

function withoutSupersededAssistantAnswer(message: ConversationMessage): ConversationMessage {
  return {
    ...message,
    content: "",
    timelineItems: message.timelineItems?.filter((item) => item.kind !== "assistant_text"),
  };
}

function consolidateSupersededSessionLiveOverlays(messages: ConversationMessage[]) {
  const overlaysByCommittedMessageId = new Map<string, ConversationMessage[]>();
  const supersededOverlays = new Set<ConversationMessage>();
  for (const message of messages) {
    if (!isSessionLiveOverlayMessage(message)) {
      continue;
    }
    const committedMessage = committedAssistantAnswerForTurn(messages, message);
    if (!committedMessage) {
      continue;
    }
    supersededOverlays.add(message);
    const overlays = overlaysByCommittedMessageId.get(committedMessage.id) ?? [];
    overlays.push(withoutSupersededAssistantAnswer(message));
    overlaysByCommittedMessageId.set(committedMessage.id, overlays);
  }
  return messages.flatMap((message) => {
    if (supersededOverlays.has(message)) {
      return [];
    }
    const overlays = overlaysByCommittedMessageId.get(message.id);
    if (!overlays?.length) {
      return [message];
    }
    return [overlays.reduce(
      (committedMessage, overlay) => mergeLiveOverlayIntoActiveTurnMessage(overlay, committedMessage),
      message,
    )];
  });
}

export function projectAgentMessageTimelineMessages({
  timelineMessages,
  activeTurnMessage,
}: AgentMessageTimelineProjectionInput): AgentMessageTimelineProjection {
  timelineMessages = withoutShadowedTerminalFailureStatuses(
    consolidateRepeatedPersistedMessages(
      timelineMessages.map(projectConversationMessageFromTurnItemsV2),
    ),
  );
  activeTurnMessage = activeTurnMessage
    ? projectConversationMessageFromTurnItemsV2(activeTurnMessage)
    : undefined;
  const projectedMessages = (() => {
    const visibleTimelineMessages = consolidateSupersededSessionLiveOverlays(
      chronologicalConversationMessages(timelineMessages)
        .filter(hasVisibleProjectionMessageContent),
    );
    if (!activeTurnMessage || hasCommittedAssistantAnswerForActiveTurn(visibleTimelineMessages, activeTurnMessage)) {
      return projectTimelineProcessMessages(visibleTimelineMessages);
    }
    let mergedActiveTurnMessage = activeTurnMessage;
    const dedupedTimelineMessages = visibleTimelineMessages.filter((message) => {
      if (isSessionLiveOverlayMessage(message) && isSameConversationTurn(message, activeTurnMessage)) {
        mergedActiveTurnMessage = projectConversationMessageFromTurnItemsV2(
          mergeLiveOverlayIntoActiveTurnMessage(message, mergedActiveTurnMessage),
        );
        return false;
      }
      return true;
    });
    const keepStreamingActiveTurnPlaceholder = shouldKeepStreamingActiveTurnPlaceholder(mergedActiveTurnMessage);
    if (!hasVisibleProjectionMessageContent(mergedActiveTurnMessage) && !keepStreamingActiveTurnPlaceholder) {
      return projectTimelineProcessMessages(dedupedTimelineMessages);
    }
    return projectTimelineProcessMessages(chronologicalConversationMessages([
      ...dedupedTimelineMessages,
      keepStreamingActiveTurnPlaceholder
        ? compactStreamingActiveTurnPlaceholderMessage(mergedActiveTurnMessage)
        : mergedActiveTurnMessage,
    ]));
  })();
  const projectedAgentMessages = projectedMessages.map(conversationMessageToAgentMessage);

  return {
    messages: projectedMessages,
    agentMessages: projectedAgentMessages,
    streamingMessages: projectedMessages.filter((message) => message.streaming),
    rowIdentities: buildAgentMessageTimelineRowIdentities(projectedAgentMessages),
  };
}
import {
  consolidateSessionTurnItemsV2,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
