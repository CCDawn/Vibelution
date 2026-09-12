import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { assistantStatusTurnItems, assistantTurnIsStreaming } from "../../routes/chatTurnProtocol";

import type { AgentMessageOperation, AgentMessageOperationGroups } from "./agentMessageOperations";
import { activeTurnStageLabel } from "./conversationActiveTurnStatusPresentation";
import { isInternalStreamingStatusStage } from "./conversationInternalStatus";
import { isRunningOperationStatus } from "./conversationOperationState";

export type ConversationFeedbackEvent = Extract<SessionTurnItem, { type: "status" | "retry" | "error" }>;

/** Attach a status operation only when the canonical TurnItems have no rendered status row. */
export function operationGroupsWithFeedbackStatusPlaceholder(
  groups: AgentMessageOperationGroups,
  message: ConversationMessage,
  lang: "zh" | "en" | string,
): AgentMessageOperationGroups {
  const operation = feedbackStatusPlaceholderOperation(message, groups.timeline, lang);
  if (!operation) {
    return groups;
  }
  return {
    timeline: [...groups.timeline, operation],
    thoughts: groups.thoughts,
    mental: groups.mental,
    tools: groups.tools,
    status: [...groups.status, operation],
  };
}

export function feedbackStatusPlaceholderOperation(
  message: ConversationMessage,
  existingOperations: AgentMessageOperation[],
  lang: "zh" | "en" | string,
): AgentMessageOperation | null {
  if (existingOperations.some(operationIsVisibleStatusProgress)) {
    return null;
  }
  const existingSequences = new Set(
    existingOperations
      .map((operation) => operation.sequence)
      .filter((sequence): sequence is number => typeof sequence === "number" && Number.isFinite(sequence)),
  );
  const statusEvents = assistantStatusTurnItems(message)
    .filter((event) => {
      const sequence = event.sequence;
      return !Number.isFinite(sequence) || sequence <= 0 || !existingSequences.has(sequence);
    })
    .filter((event) => shouldUseFeedbackStatusPlaceholder(event, assistantTurnIsStreaming(message)));
  const event = statusEvents[statusEvents.length - 1];
  if (!event) {
    return null;
  }
  const sequence = Number(event.sequence ?? 0);
  const rawName = statusEventName(event);
  const summary = isActiveInternalStreamingStatus(event, assistantTurnIsStreaming(message))
    ? ""
    : statusEventSummary(event);
  return {
    id: `${message.id}-feedback-status-placeholder-${sequence > 0 ? sequence : statusEvents.length}`,
    kind: "status",
    label: feedbackStatusPlaceholderLabel(event, lang),
    rawLabel: rawName,
    status: event.status,
    rawStatus: event.status,
    summary,
    durationSeconds: null,
    resultPreview: summary || undefined,
    error: event.type === "error" ? event.text : undefined,
    sequence: sequence > 0 ? sequence : undefined,
    timestamp: event.updatedAt ?? event.createdAt,
  };
}

export function operationIsVisibleStatusProgress(operation: AgentMessageOperation) {
  if (operation.kind !== "status") {
    return false;
  }
  const combined = [
    operation.rawLabel,
    operation.label,
    operation.summary,
    operation.resultPreview,
  ].map((value) => String(value ?? "").trim().toLowerCase()).filter(Boolean).join(" ");
  return combined.includes("long_loop_progress")
    || combined.includes("尚未形成最终回答")
    || combined.includes("本轮尚未形成最终回答")
    || combined.includes("工具循环")
    || combined.includes("tool loop");
}

export function shouldUseFeedbackStatusPlaceholder(event: ConversationFeedbackEvent, _streaming: boolean) {
  if (statusEventHasDiagnostic(event)) {
    return true;
  }
  return event.type === "retry" || feedbackStatusIsLongLoopProgress(event);
}

export function isActiveInternalStreamingStatus(event: ConversationFeedbackEvent, streaming: boolean) {
  return streaming
    && isRunningOperationStatus(event.status)
    && isInternalStreamingStatusStage(statusEventName(event));
}

function statusEventName(event: ConversationFeedbackEvent) {
  return event.type === "status" ? event.code : event.type === "retry" ? "model_retry" : event.code;
}

function statusEventText(event: ConversationFeedbackEvent) {
  return event.type === "retry" ? event.reason : event.text;
}

export function feedbackStatusPlaceholderLabel(event: ConversationFeedbackEvent, lang: "zh" | "en" | string) {
  if (feedbackStatusIsLongLoopProgress(event)) {
    return lang !== "en" ? "工具循环" : "Tool loop";
  }
  return activeTurnStageLabel(statusEventName(event), lang);
}

export function feedbackStatusIsLongLoopProgress(event: ConversationFeedbackEvent) {
  return statusEventCombinedText(event).toLowerCase().includes("long_loop_progress")
    || statusEventCombinedText(event).includes("工具循环")
    || statusEventCombinedText(event).includes("尚未形成最终回答");
}

export function statusEventHasDiagnostic(event: ConversationFeedbackEvent) {
  const status = event.status;
  return Boolean(
    event.type === "error"
    || ["failed", "error", "failure", "timeout", "timed_out", "cancelled"].includes(status)
    || ["degraded", "fallback", "partial", "recovered", "unavailable"].includes(status),
  );
}

export function statusEventCombinedText(event: ConversationFeedbackEvent) {
  return [
    statusEventName(event),
    event.summary,
    statusEventText(event),
  ].map((value) => String(value ?? "").trim()).filter(Boolean).join("\n");
}

export function statusEventSummary(event: ConversationFeedbackEvent) {
  return String(event.summary || statusEventText(event) || "").trim();
}

export function statusEventResultPreview(event: ConversationFeedbackEvent) {
  return statusEventText(event).trim();
}
