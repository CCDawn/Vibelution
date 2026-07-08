import type {
  ConversationMessage,
  MentalStateSnapshot,
  ToolCall,
} from "../api/types";
import {
  isInternalStreamingStatusContent,
  isInternalStreamingStatusStage,
} from "../components/conversation/conversationInternalStatus";
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
  return mergeAgentFeedbackEvents(message.feedbackEvents)
    .sort((left, right) => normalizedSequence(left.sequence) - normalizedSequence(right.sequence))
    .map((event, index) => feedbackEventToAgentPart(message, event, index))
    .filter((part): part is AgentMessagePart => part !== null);
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
  return runtimeEventToAgentPart(id, event);
}

function runtimeEventToAgentPart(id: string, event: AgentFeedbackEvent): AgentRuntimeEventPart | null {
  if (isInternalRuntimePipelineEvent(event) && !eventHasTemporaryErrorInfo(event)) {
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
    sequence: event.sequence || undefined,
    timestamp: event.timestamp,
    tracePath: event.tracePath,
  };
}

const INTERNAL_RUNTIME_EVENT_NAME_ALIASES = new Set([
  "retrying",
]);

function isInternalRuntimePipelineEvent(event: AgentFeedbackEvent) {
  if (event.kind !== "status") {
    return false;
  }
  const name = compactText(event.name).toLowerCase();
  if (isInternalStreamingStatusStage(name) || INTERNAL_RUNTIME_EVENT_NAME_ALIASES.has(name)) {
    return true;
  }
  return isInternalStreamingStatusContent([
    event.summary,
    event.resultPreview,
  ].map(compactText).filter(Boolean).join(" "));
}

function eventHasTemporaryErrorInfo(event: AgentFeedbackEvent) {
  const status = compactText(event.status).toLowerCase();
  return Boolean(
    compactText(event.error)
    || compactText(event.failureClass)
    || event.timedOut
    || ["error", "errored", "failed", "failure", "timeout", "timed_out"].includes(status),
  );
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

function legacyThoughtPartForMessage(message: ConversationMessage): AgentThoughtPart[] {
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
    durationMs: optionalNumber(toolCall.durationMs),
    durationSeconds: legacyToolDurationSeconds(toolCall),
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
  }));
}

function legacyToolDurationSeconds(toolCall: ToolCall) {
  return optionalNumber(toolCall.durationSeconds)
    ?? optionalNumber((toolCall as ToolCall & { elapsedSeconds?: unknown }).elapsedSeconds);
}

function optionalNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
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

function mentalSnapshotSummary(snapshot: MentalStateSnapshot | undefined) {
  if (!snapshot) {
    return "";
  }
  return [
    snapshot.summary,
    snapshot.feeling,
    snapshot.whisper,
    snapshot.intervention,
    snapshot.cognitiveState ? `state: ${snapshot.cognitiveState}` : "",
  ]
    .map(compactText)
    .find(Boolean) ?? "";
}
