import type { ConversationMessage } from "../api/types";
import { answerProjectionContent } from "../components/conversation/conversationInternalStatus";
import { shouldDisplayRuntimeStatus } from "../components/conversation/conversationDisplayProtocol";
import { mergeAgentFeedbackEvents, type AgentFeedbackEvent } from "./agentFeedbackEvents";
import type {
  AgentMentalPart,
  AgentMessage,
  AgentMessagePart,
  AgentRuntimeEventPart,
  AgentThoughtPart,
  AgentToolCallPart,
} from "./types";

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
  const feedbackParts = feedbackPartsForMessage(message);
  return [
    ...feedbackParts,
    ...activeTurnThoughtPartForMessage(message, feedbackParts),
  ];
}

function feedbackPartsForMessage(message: ConversationMessage): AgentMessagePart[] {
  return mergeAgentFeedbackEvents(message.feedbackEvents)
    .sort((left, right) => normalizedSequence(left.sequence) - normalizedSequence(right.sequence))
    .map((event, index) => feedbackEventToAgentPart(message, event, index))
    .filter((part): part is AgentMessagePart => part !== null);
}

function activeTurnThoughtPartForMessage(
  message: ConversationMessage,
  feedbackParts: AgentMessagePart[],
): AgentThoughtPart[] {
  if (message.metadata?.kind !== "session_active_turn_layer") {
    return [];
  }
  if (feedbackParts.some((part) => part.type === "thought")) {
    return [];
  }
  const thought = compactText(message.thought);
  if (!thought || isInternalThoughtPlaceholder(thought, thought)) {
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

function feedbackEventToAgentPart(
  message: ConversationMessage,
  event: AgentFeedbackEvent,
  index: number,
): AgentMessagePart | null {
  const id = `${message.id}-feedback-${event.sequence || index + 1}`;
  if (event.kind === "thought") {
    const text = compactText(event.resultPreview ?? event.summary);
    const summary = compactText(event.summary);
    if (!text || isInternalThoughtPlaceholder(text, summary)) {
      return null;
    }
    return text
      ? {
          id,
          type: "thought",
          text,
          summary,
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
  return runtimeEventToAgentPart(message, id, event);
}

function runtimeEventToAgentPart(
  message: ConversationMessage,
  id: string,
  event: AgentFeedbackEvent,
): AgentRuntimeEventPart | null {
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
    return null;
  }
  return {
    id,
    type: "runtime-event",
    kind: event.kind,
    name: event.name,
    status: event.status || "running",
    summary: compactText(event.summary),
    resultPreview: event.resultPreview,
    error: event.error,
    failureClass: event.failureClass,
    transportStatus: event.transportStatus,
    sequence: event.sequence || undefined,
    timestamp: event.timestamp,
    tracePath: event.tracePath,
  };
}

function toolEventToAgentPart(id: string, event: AgentFeedbackEvent): AgentToolCallPart {
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
  };
}

function textPartForMessage(message: ConversationMessage): AgentMessagePart[] {
  const text = String(message.role === "assistant" ? answerProjectionContent(message) : message.content).trim();
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

function isInternalThoughtPlaceholder(text: string, summary: string) {
  const normalizedText = text.trim().toLowerCase();
  const normalizedSummary = summary.trim().toLowerCase();
  if (!normalizedText) {
    return true;
  }
  if (["internal", "internal_thought", "internal reasoning", "internal process"].includes(normalizedText)) {
    return true;
  }
  return normalizedText === normalizedSummary && normalizedText.startsWith("internal");
}
