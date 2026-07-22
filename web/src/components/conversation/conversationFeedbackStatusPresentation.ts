import type { ConversationMessage } from "../../api/types";

import type { AgentMessageOperation, AgentMessageOperationGroups } from "./agentMessageOperations";
import { isInternalStreamingStatusStage } from "./conversationInternalStatus";
import { isRunningOperationStatus } from "./conversationOperationState";

export type ConversationFeedbackEvent = NonNullable<ConversationMessage["feedbackEvents"]>[number];

/** Attach a synthetic status operation from message feedbackEvents when timeline lacks one. */
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
  const statusEvents = (message.feedbackEvents ?? [])
    .filter((event) => event.kind === "status")
    .filter((event) => {
      const sequence = Number(event.sequence ?? 0);
      return !Number.isFinite(sequence) || sequence <= 0 || !existingSequences.has(sequence);
    })
    .filter((event) => shouldUseFeedbackStatusPlaceholder(event, Boolean(message.streaming)));
  const event = statusEvents[statusEvents.length - 1];
  if (!event) {
    return null;
  }
  const sequence = Number(event.sequence ?? 0);
  const rawName = String(event.name || "status").trim();
  const summary = isActiveInternalStreamingStatus(event, Boolean(message.streaming))
    ? ""
    : statusEventSummary(event);
  return {
    id: `${message.id}-feedback-status-placeholder-${sequence > 0 ? sequence : statusEvents.length}`,
    kind: "status",
    label: feedbackStatusPlaceholderLabel(event, lang),
    rawLabel: rawName,
    status: String(event.status || (message.streaming ? "running" : "done")).trim() || "running",
    rawStatus: String(event.status || "").trim() || undefined,
    summary,
    durationSeconds: null,
    resultPreview: summary || undefined,
    error: typeof event.error === "string" ? event.error : undefined,
    sequence: sequence > 0 ? sequence : undefined,
    timestamp: event.timestamp,
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

export function shouldUseFeedbackStatusPlaceholder(event: ConversationFeedbackEvent, streaming: boolean) {
  if (statusEventHasDiagnostic(event)) {
    return true;
  }
  return feedbackStatusIsLongLoopProgress(event) || isActiveInternalStreamingStatus(event, streaming);
}

export function isActiveInternalStreamingStatus(event: ConversationFeedbackEvent, streaming: boolean) {
  return streaming
    && isRunningOperationStatus(String(event.status ?? ""))
    && isInternalStreamingStatusStage(event.name);
}

export function feedbackStatusPlaceholderLabel(event: ConversationFeedbackEvent, lang: "zh" | "en" | string) {
  const zh = lang !== "en";
  const stage = String(event.name ?? "").trim().toLowerCase();
  const combined = statusEventCombinedText(event).toLowerCase();
  if (feedbackStatusIsLongLoopProgress(event)) {
    return zh ? "工具循环" : "Tool loop";
  }
  if (stage === "context_prepare") {
    return zh ? "准备上下文" : "Preparing context";
  }
  if (stage === "queued") {
    return zh ? "等待执行" : "Queued";
  }
  if (stage === "agent_prepare") {
    return zh ? "准备 Agent" : "Preparing agent";
  }
  if (stage === "history_restore") {
    return zh ? "恢复会话" : "Restoring session";
  }
  if (stage === "followup_prepare") {
    return zh ? "准备下一步" : "Preparing next step";
  }
  if (combined.includes("model_thinking") || combined.includes("正在思考") || combined.includes("reasoning")) {
    return zh ? "模型思考" : "Model thinking";
  }
  if (combined.includes("model_request") || combined.includes("请求模型")) {
    return zh ? "请求模型" : "Request model";
  }
  if (combined.includes("retrying") || combined.includes("model_retry") || combined.includes("模型连接正在重试")) {
    return zh ? "请求重试" : "Request retry";
  }
  return zh ? "运行状态" : "Runtime status";
}

export function feedbackStatusIsLongLoopProgress(event: ConversationFeedbackEvent) {
  return statusEventCombinedText(event).toLowerCase().includes("long_loop_progress")
    || statusEventCombinedText(event).includes("工具循环")
    || statusEventCombinedText(event).includes("尚未形成最终回答");
}

export function statusEventHasDiagnostic(event: ConversationFeedbackEvent) {
  const status = String(event.status ?? "").trim().toLowerCase();
  return Boolean(
    event.error
    || event.failureClass
    || event.timedOut
    || ["failed", "error", "failure", "timeout", "timed_out", "cancelled"].includes(status)
    || ["degraded", "fallback", "partial", "recovered", "unavailable"].includes(status),
  );
}

export function statusEventCombinedText(event: ConversationFeedbackEvent) {
  return [
    event.name,
    event.summary,
    event.resultPreview,
  ].map((value) => String(value ?? "").trim()).filter(Boolean).join("\n");
}

export function statusEventSummary(event: ConversationFeedbackEvent) {
  return String(event.summary || event.resultPreview || "").trim();
}

export function statusEventResultPreview(event: ConversationFeedbackEvent) {
  return String(event.resultPreview || "").trim();
}
