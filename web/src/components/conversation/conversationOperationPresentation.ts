/**
 * Conversation operation / process presentation pure helpers (structure C3.1).
 * Pure: no React / DOM.
 */
import type { AgentMessageOperation, AgentMessageOperationKind } from "./agentMessageOperations";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import type { CodexRolloutTraceEvent } from "./codexRolloutTrace";

export function compactConversationPreview(value: string, maxLength = 180) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
}

export function operationVisualTone(operation: Pick<AgentMessageOperation, "kind">) {
  if (operation.kind === "thought") {
    return "thought" as const;
  }
  if (operation.kind === "mental") {
    return "mental" as const;
  }
  if (operation.kind === "status") {
    return "status" as const;
  }
  return "tool" as const;
}

export function operationStatusToneClassNameFromTone(tone: string) {
  if (tone === "done") {
    return "success";
  }
  if (tone === "degraded") {
    return "warning";
  }
  return tone;
}

export function operationStatusFallbackText(
  status: string,
  lang: "zh" | "en",
  statusLabel: (status: string) => string,
) {
  const normalized = status.trim().toLowerCase();
  const explicitFallbackLabels: Record<string, string> = {
    degraded: lang === "zh" ? "降级" : "Degraded",
    fallback: lang === "zh" ? "备用路径" : "Fallback",
    partial: lang === "zh" ? "部分结果" : "Partial",
    recovered: lang === "zh" ? "已恢复" : "Recovered",
    unavailable: lang === "zh" ? "不可用" : "Unavailable",
  };
  return explicitFallbackLabels[normalized] ?? statusLabel(status);
}

export function rolloutTraceEventLabel(
  kind: CodexRolloutTraceEvent["kind"],
  lang: "zh" | "en",
) {
  const labels: Record<CodexRolloutTraceEvent["kind"], string> = {
    ToolCallStarted: lang === "zh" ? "调用开始" : "Tool call started",
    RuntimeStarted: lang === "zh" ? "运行开始" : "Runtime started",
    RuntimeEnded: lang === "zh" ? "运行结束" : "Runtime ended",
    ToolCallEnded: lang === "zh" ? "调用结束" : "Tool call ended",
  };
  return labels[kind];
}

export function operationGroupTitle(
  kind: AgentMessageOperationKind,
  count: number,
  labels: { thoughtProcess: string; mentalProcess: string; toolProcess: string },
) {
  if (kind === "thought") {
    return labels.thoughtProcess;
  }
  if (kind === "mental") {
    return labels.mentalProcess;
  }
  return `${labels.toolProcess} ${count}`;
}

export function operationTimelineTitle(
  operations: Array<Pick<AgentMessageOperation, "kind">>,
  lang: "zh" | "en",
  labels: { thoughtProcess: string; mentalProcess: string; toolProcess: string },
) {
  if (operations.length > 0) {
    return lang === "zh" ? "执行过程" : "Execution trace";
  }
  const thoughtCount = operations.filter((operation) => operation.kind === "thought").length;
  const toolCount = operations.filter((operation) => operation.kind === "tool").length;
  const mentalCount = operations.filter((operation) => operation.kind === "mental").length;
  const parts = [
    thoughtCount > 0 ? `${labels.thoughtProcess} ${thoughtCount}` : "",
    toolCount > 0 ? `${labels.toolProcess} ${toolCount}` : "",
    mentalCount > 0 ? `${labels.mentalProcess} ${mentalCount}` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : `${labels.toolProcess} ${operations.length}`;
}

export function shouldRenderCodexTranscriptSurface(surface?: CodexTranscriptSurface) {
  return surface?.mode === "native" && surface.cells.length > 0;
}

export function shouldRenderCompactActiveTurnPlaceholder(input: {
  role: string;
  streaming: boolean;
  showResponseBlock: boolean;
  hasFeedbackTimeline: boolean;
  hasActiveProcess: boolean;
  turnErrorMessage: boolean;
}) {
  return Boolean(
    input.role === "assistant"
    && input.streaming
    && !input.showResponseBlock
    && !input.hasFeedbackTimeline
    && !input.hasActiveProcess
    && !input.turnErrorMessage,
  );
}
