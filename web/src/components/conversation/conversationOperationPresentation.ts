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

export type OperationStatusIconKind = "done" | "running" | "running_static" | "idle";

export function operationStatusIconKind(
  status: string,
  isRunning: boolean,
  animateRunning = true,
): OperationStatusIconKind {
  const normalized = status.trim().toLowerCase();
  if (["done", "success", "completed", "succeeded"].includes(normalized)) {
    return "done";
  }
  if (isRunning) {
    return animateRunning ? "running" : "running_static";
  }
  return "idle";
}

export type ProcessSummaryIconKind = "running" | "failed" | "degraded" | "done" | "default";

export function processSummaryIconKind(tone: string): ProcessSummaryIconKind {
  if (tone === "running") {
    return "running";
  }
  if (tone === "failed") {
    return "failed";
  }
  if (tone === "degraded") {
    return "degraded";
  }
  if (tone === "done") {
    return "done";
  }
  return "default";
}

export function hasOperationDetails(operation: {
  arguments?: Record<string, unknown> | null;
  resultPreview?: unknown;
  error?: unknown;
  resultType?: unknown;
  resultLength?: unknown;
  timeoutSeconds?: unknown;
  tracePath?: unknown;
}) {
  return Boolean(
    Object.keys(operation.arguments ?? {}).length
    || operation.resultPreview
    || operation.error
    || operation.resultType
    || operation.resultLength !== undefined
    || operation.timeoutSeconds !== undefined
    || operation.tracePath,
  );
}
