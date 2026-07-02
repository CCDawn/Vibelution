import type {
  ConversationFeedbackEvent,
  ConversationMessage,
  MentalStateSnapshot,
  ToolCall,
} from "../api/types";
import { mergeConversationFeedbackEvents } from "../components/conversation/conversationFeedbackEvents";
import type {
  AgentMentalPart,
  AgentMessage,
  AgentMessagePart,
  AgentRuntimeEventPart,
  AgentThread,
  AgentThreadSource,
  AgentThoughtPart,
  AgentToolCallPart,
} from "./types";

export type ConversationMessagesToAgentThreadOptions = {
  source?: AgentThreadSource;
};

export function conversationMessagesToAgentThread(
  id: string,
  messages: ConversationMessage[],
  options: ConversationMessagesToAgentThreadOptions = {},
): AgentThread {
  const agentMessages = messages.map(conversationMessageToAgentMessage);
  return {
    id,
    source: options.source ?? { kind: "conversation", id },
    status: agentMessages.some((message) => message.streaming) ? "streaming" : "idle",
    messages: agentMessages,
  };
}

export function conversationMessageToAgentMessage(message: ConversationMessage): AgentMessage {
  const parts = conversationMessageToAgentParts(message);
  return {
    id: message.id,
    role: message.role,
    createdAt: message.timestamp,
    streaming: Boolean(message.streaming),
    turnId: messageTurnId(message),
    source: {
      kind: "conversation-message",
      id: message.id,
      metadata: message.metadata,
    },
    parts,
    metadata: message.metadata,
  };
}

export function conversationMessageToAgentParts(message: ConversationMessage): AgentMessagePart[] {
  if (message.role === "user") {
    return [
      ...textPartForMessage(message),
      ...attachmentPartsForMessage(message),
      ...referencePartsForMessage(message),
    ];
  }

  return [
    ...processPartsForAssistantMessage(message),
    ...textPartForMessage(message),
    ...attachmentPartsForMessage(message),
    ...referencePartsForMessage(message),
  ];
}

function processPartsForAssistantMessage(message: ConversationMessage): AgentMessagePart[] {
  if (message.role !== "assistant") {
    return [];
  }
  if ((message.feedbackEvents?.length ?? 0) > 0) {
    const feedbackParts = feedbackPartsForMessage(message);
    const feedbackPartTypes = new Set(feedbackParts.map((part) => part.type));
    return [
      ...feedbackParts,
      ...(feedbackPartTypes.has("thought") ? [] : legacyThoughtPartForMessage(message)),
      ...(feedbackPartTypes.has("mental") ? [] : legacyMentalPartForMessage(message)),
      ...(feedbackPartTypes.has("tool-call") ? [] : legacyToolPartsForMessage(message)),
    ];
  }
  return [
    ...legacyThoughtPartForMessage(message),
    ...legacyMentalPartForMessage(message),
    ...legacyToolPartsForMessage(message),
  ];
}

function feedbackPartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  return mergeConversationFeedbackEvents(message.feedbackEvents)
    .sort((left, right) => normalizedSequence(left.sequence) - normalizedSequence(right.sequence))
    .map((event, index) => feedbackEventToAgentPart(message, event, index))
    .filter((part): part is AgentMessagePart => part !== null);
}

function feedbackEventToAgentPart(
  message: ConversationMessage,
  event: ConversationFeedbackEvent,
  index: number,
): AgentMessagePart | null {
  const id = `${message.id}-feedback-${event.sequence || index + 1}`;
  if (event.kind === "thought") {
    return compactText(event.resultPreview ?? event.summary)
      ? {
          id,
          type: "thought",
          text: compactText(event.resultPreview ?? event.summary),
          summary: compactText(event.summary),
          status: event.status || assistantStatus(message),
          sequence: event.sequence || undefined,
          timestamp: event.timestamp,
        }
      : null;
  }
  if (event.kind === "mental") {
    return {
      id,
      type: "mental",
      status: event.status || assistantStatus(message),
      summary: compactText(event.summary ?? event.resultPreview),
      sequence: event.sequence || undefined,
      timestamp: event.timestamp,
    } satisfies AgentMentalPart;
  }
  if (event.kind === "tool") {
    return toolEventToAgentPart(id, event);
  }
  return runtimeEventToAgentPart(id, event);
}

function runtimeEventToAgentPart(id: string, event: ConversationFeedbackEvent): AgentRuntimeEventPart {
  return {
    id,
    type: "runtime-event",
    kind: event.kind,
    name: event.name,
    status: event.status || "running",
    summary: compactText(event.summary),
    resultPreview: event.resultPreview,
    error: event.error,
    sequence: event.sequence || undefined,
    timestamp: event.timestamp,
    tracePath: event.tracePath,
  };
}

function toolEventToAgentPart(id: string, event: ConversationFeedbackEvent): AgentToolCallPart {
  return {
    id,
    type: "tool-call",
    name: event.name?.trim() || "tool",
    status: event.status || "done",
    summary: compactText(event.summary),
    arguments: event.arguments,
    resultPreview: event.resultPreview,
    resultType: event.resultType,
    resultLength: event.resultLength,
    error: event.error,
    durationMs: event.durationMs,
    durationSeconds: event.durationSeconds,
    timeoutSeconds: event.timeoutSeconds,
    transportStatus: event.transportStatus,
    semanticStatus: event.semanticStatus,
    exitCode: event.exitCode,
    timedOut: event.timedOut,
    failureClass: event.failureClass,
    resultKind: event.resultKind,
    truncated: event.truncated,
    originalLength: event.originalLength,
    tracePath: event.tracePath,
    sequence: event.sequence || undefined,
    timestamp: event.timestamp,
    relatedThoughtSequence: event.relatedThoughtSequence,
    source: "feedback-event",
    original: event,
  };
}

function legacyThoughtPartForMessage(message: ConversationMessage): AgentThoughtPart[] {
  const thought = compactText(message.thought);
  if (!thought) {
    return [];
  }
  return [{
    id: `${message.id}-thought`,
    type: "thought",
    text: thought,
    summary: thought,
    status: assistantStatus(message),
  }];
}

function legacyMentalPartForMessage(message: ConversationMessage): AgentMentalPart[] {
  const summary = mentalSnapshotSummary(message.mentalSnapshot);
  if (!summary) {
    return [];
  }
  return [{
    id: `${message.id}-mental`,
    type: "mental",
    status: assistantStatus(message),
    snapshot: message.mentalSnapshot,
    summary,
  }];
}

function legacyToolPartsForMessage(message: ConversationMessage): AgentToolCallPart[] {
  return (message.toolCalls ?? []).map((toolCall, index) => ({
    id: `${message.id}-tool-${index}`,
    type: "tool-call",
    name: toolCall.name?.trim() || "tool",
    status: toolCall.status || "done",
    summary: compactText(toolCall.summary),
    arguments: toolCall.arguments,
    resultPreview: toolCall.resultPreview,
    resultType: toolCall.resultType,
    resultLength: toolCall.resultLength,
    error: toolCall.error,
    durationMs: toolCall.durationMs,
    durationSeconds: toolCall.durationSeconds,
    timeoutSeconds: toolCall.timeoutSeconds,
    transportStatus: toolCall.transportStatus,
    semanticStatus: toolCall.semanticStatus,
    exitCode: toolCall.exitCode,
    timedOut: toolCall.timedOut,
    failureClass: toolCall.failureClass,
    resultKind: toolCall.resultKind,
    truncated: toolCall.truncated,
    originalLength: toolCall.originalLength,
    tracePath: toolCall.tracePath,
    source: "legacy-tool-call",
    original: toolCall,
  }));
}

function textPartForMessage(message: ConversationMessage): AgentMessagePart[] {
  const text = String(message.content ?? "").trim();
  if (!text) {
    return [];
  }
  return [{
    id: `${message.id}-text`,
    type: "text",
    channel: message.role === "assistant" ? "answer" : "user",
    text,
  }];
}

function attachmentPartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  return (message.attachments ?? []).map((attachment, index) => ({
    id: `${message.id}-attachment-${attachment.artifactId || index}`,
    type: "attachment",
    attachment,
  }));
}

function referencePartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  return (message.references ?? []).map((reference, index) => ({
    id: `${message.id}-reference-${reference.referenceId || reference.sessionId || index}`,
    type: "reference",
    reference,
  }));
}

function assistantStatus(message: ConversationMessage) {
  return message.streaming ? "running" : "done";
}

function messageTurnId(message: ConversationMessage) {
  const value = message.metadata?.turnId;
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  return trimmed.startsWith("live:") ? trimmed.slice("live:".length) : trimmed;
}

function normalizedSequence(value: unknown) {
  const numeric = Number(value ?? 0);
  return Number.isFinite(numeric) ? numeric : 0;
}

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function mentalSnapshotSummary(snapshot: MentalStateSnapshot | undefined) {
  if (!snapshot) {
    return "";
  }
  return [
    snapshot.feeling,
    snapshot.summary,
    snapshot.whisper,
    snapshot.intervention,
    snapshot.cognitiveState ? `state: ${snapshot.cognitiveState}` : "",
  ]
    .map(compactText)
    .find(Boolean) ?? "";
}
