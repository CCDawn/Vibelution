import type { AgentMessage, AgentMessagePart, AgentTextPart } from "../../agent-thread/types";
import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageTimelineItem, AgentMessageTimelineItemStatus } from "./agentMessageTimeline";
import { buildCodexRolloutTraceEvents, type CodexRolloutTraceEvent } from "./codexRolloutTrace";
import { buildCodexToolLifecycleModel, type CodexToolLifecycleModel } from "./codexToolLifecycleModel";
import { shouldDisplayTranscriptCell } from "./conversationDisplayProtocol";
import { isInternalStreamingStatusContent } from "./conversationInternalStatus";

export type CodexTranscriptCellKind =
  | "user"
  | "assistant_markdown"
  | "reasoning_summary"
  | "tool_call"
  | "status"
  | "error_notice"
  | "stream_tail";

export type CodexTranscriptCellStatus = "pending" | "running" | "completed" | "failed" | "degraded";

export type CodexTranscriptCellTone = "neutral" | "running" | "warning" | "error";

export type CodexTranscriptCell = {
  id: string;
  kind: CodexTranscriptCellKind;
  messageId: string;
  status: CodexTranscriptCellStatus;
  tone: CodexTranscriptCellTone;
  channel?: string;
  phase?: string;
  terminal?: boolean;
  provisional?: boolean;
  diagnosticSummary?: Record<string, unknown>;
  title?: string;
  text?: string;
  summary?: string;
  operationIds?: string[];
  rolloutTraceEvents?: CodexRolloutTraceEvent[];
  toolLifecycleModel?: CodexToolLifecycleModel;
  sourceItemId?: string;
};

export type CodexTranscriptCellBuildOptions = {
  operations?: AgentMessageOperation[];
  timelineItems?: AgentMessageTimelineItem[];
  includeStreamTail?: boolean;
};

export function buildCodexTranscriptCells(
  message: AgentMessage,
  options: CodexTranscriptCellBuildOptions = {},
): CodexTranscriptCell[] {
  if (message.role === "user") {
    return userTranscriptCells(message);
  }
  if (message.role !== "assistant") {
    return [];
  }

  const cells = (options.timelineItems?.length
    ? cellsFromTimelineItems(message.id, options.timelineItems)
    : cellsFromOperations(message.id, options.operations ?? []))
    .filter(shouldDisplayTranscriptCell);
  if (!hasAssistantMarkdownCell(cells)) {
    const answerText = answerTextFromMessage(message);
    if (answerText) {
      cells.push({
        id: `${message.id}-assistant-markdown`,
        kind: "assistant_markdown",
        messageId: message.id,
        status: message.streaming ? "running" : "completed",
        tone: message.streaming ? "running" : "neutral",
        text: answerText,
      });
    }
  }
  if (shouldAddStreamTail(message, cells, options.includeStreamTail)) {
    cells.push({
      id: `${message.id}-stream-tail`,
      kind: "stream_tail",
      messageId: message.id,
      status: "running",
      tone: "running",
    });
  }
  return cells;
}

function userTranscriptCells(message: AgentMessage): CodexTranscriptCell[] {
  const text = message.parts
    .filter(isUserTextPart)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
  if (!text) {
    return [];
  }
  return [
    {
      id: `${message.id}-user`,
      kind: "user",
      messageId: message.id,
      status: "completed",
      tone: "neutral",
      text,
    },
  ];
}

function cellsFromTimelineItems(
  messageId: string,
  timelineItems: AgentMessageTimelineItem[],
): CodexTranscriptCell[] {
  return timelineItems
    .map((item): CodexTranscriptCell | null => {
      if (item.kind === "thought") {
        const status = normalizeCellStatus(item.status);
        return {
          id: `${messageId}-${item.id}`,
          kind: "reasoning_summary",
          messageId,
          status,
          tone: cellTone(status),
          text: item.text,
          summary: item.preview || item.text,
          operationIds: [...item.sourceOperationIds],
          sourceItemId: item.id,
        };
      }
      if (item.kind === "assistant_text") {
        const status = normalizeCellStatus(item.status);
        return {
          id: `${messageId}-${item.id}`,
          kind: "assistant_markdown",
          messageId,
          status,
          tone: cellTone(status),
          text: item.text,
          sourceItemId: item.id,
        };
      }
      if (item.kind === "command_group") {
        const status = normalizeCellStatus(item.status);
        const operationIds = item.operations.map((operation) => operation.id);
        return {
          id: `${messageId}-${item.id}`,
          kind: status === "failed" ? "error_notice" : "tool_call",
          messageId,
          status,
          tone: cellTone(status),
          title: item.title,
          summary: item.summary,
          operationIds,
          toolLifecycleModel: buildCodexToolLifecycleModel(item.operations),
          rolloutTraceEvents: buildCodexRolloutTraceEvents(item.operations),
          sourceItemId: item.id,
        };
      }
      if (item.kind === "operation") {
        return cellFromOperation(messageId, item.operation, item.id, item.status, item.title, item.summary);
      }
      return null;
    })
    .filter((cell): cell is CodexTranscriptCell => cell !== null);
}

function cellsFromOperations(
  messageId: string,
  operations: AgentMessageOperation[],
): CodexTranscriptCell[] {
  return operations
    .filter((operation) => operation.kind !== "thought" && operation.kind !== "mental")
    .map((operation) => cellFromOperation(messageId, operation));
}

function cellFromOperation(
  messageId: string,
  operation: AgentMessageOperation,
  sourceItemId?: string,
  timelineStatus?: AgentMessageTimelineItemStatus,
  timelineTitle?: string,
  timelineSummary?: string,
): CodexTranscriptCell {
  const status = normalizeCellStatus(timelineStatus ?? operation.status);
  const failurePresentation = status === "failed"
    ? toolFailurePresentation(operation, timelineSummary)
    : null;
  const kind = status === "failed"
    ? "error_notice"
    : operation.kind === "status"
      ? "status"
      : "tool_call";
  return {
    id: `${messageId}-${sourceItemId ?? operation.id}`,
    kind,
    messageId,
    status,
    tone: cellTone(status),
    title: timelineTitle || operation.label,
    summary: failurePresentation
      ? failurePresentation.summary
      : compactText(timelineSummary || operation.summary),
    diagnosticSummary: failurePresentation?.diagnosticSummary,
    operationIds: [operation.id],
    toolLifecycleModel: operation.kind === "tool" ? buildCodexToolLifecycleModel(operation) : undefined,
    rolloutTraceEvents: buildCodexRolloutTraceEvents(operation),
    sourceItemId,
  };
}

type ToolFailurePresentation = {
  summary: string;
  diagnosticSummary?: Record<string, unknown>;
};

function toolFailurePresentation(
  operation: AgentMessageOperation,
  timelineSummary?: string,
): ToolFailurePresentation {
  const candidates = [operation.error, timelineSummary, operation.summary, operation.resultPreview];
  for (const candidate of candidates) {
    const structured = structuredToolFailurePresentation(candidate);
    if (structured) {
      return structured;
    }
  }
  return { summary: compactFailureText(operation.error || timelineSummary || operation.summary) };
}

function structuredToolFailurePresentation(value: string | undefined): ToolFailurePresentation | null {
  const payload = parseJsonObject(value);
  if (!payload || recordText(payload, "status").toLowerCase() !== "error") {
    return null;
  }
  const code = recordText(payload, "error");
  const message = recordText(payload, "message");
  if (!code && !message) {
    return null;
  }
  const target = recordTarget(payload);
  const recovery = structuredToolFailureRecovery(code);
  const detail = [
    target ? `目标：${target}` : "",
    recovery ? `建议：${recovery}` : "",
  ].filter(Boolean).join("\n");
  return {
    summary: structuredToolFailureSummary(code, message),
    diagnosticSummary: {
      ...(code ? { reasonCode: code } : {}),
      ...(message ? { reasonSummary: message } : {}),
      ...(detail ? { reasonDetail: detail } : {}),
    },
  };
}

function parseJsonObject(value: string | undefined): Record<string, unknown> | null {
  const trimmed = String(value ?? "").trim();
  if (!trimmed.startsWith("{") || !trimmed.endsWith("}")) {
    return null;
  }
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null;
  } catch {
    return null;
  }
}

function recordText(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "string" ? value.trim() : "";
}

function recordTarget(record: Record<string, unknown>) {
  const target = record.target;
  if (typeof target === "string") {
    return target.trim();
  }
  if (!target || typeof target !== "object" || Array.isArray(target)) {
    return "";
  }
  const targetRecord = target as Record<string, unknown>;
  return recordText(targetRecord, "filePath") || recordText(targetRecord, "symbol");
}

function structuredToolFailureSummary(code: string, message: string) {
  const summaries: Record<string, string> = {
    target_not_indexed: "索引未就绪",
    directory_not_indexed: "目录未建立索引",
    target_not_found: "目标不存在",
    target_outside_project: "目标超出项目范围",
  };
  return summaries[code] || compactFailureText(message || code || "执行失败");
}

function structuredToolFailureRecovery(code: string) {
  if (code === "target_not_indexed") {
    return "刷新索引后重试";
  }
  if (code === "directory_not_indexed") {
    return "确认目录属于索引范围后重试";
  }
  return "";
}

function compactFailureText(value: string | undefined) {
  const normalized = compactText(value);
  const maxLength = 96;
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength - 1).trimEnd()}…`
    : normalized;
}

function answerTextFromMessage(message: AgentMessage) {
  const text = message.parts
    .filter(isAssistantAnswerTextPart)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
  return isInternalStreamingStatusContent(text) ? "" : text;
}

function shouldAddStreamTail(
  message: AgentMessage,
  cells: CodexTranscriptCell[],
  includeStreamTail = true,
) {
  if (!includeStreamTail || !message.streaming) {
    return false;
  }
  const hasRunningCell = cells.some((cell) => cell.status === "running" || cell.status === "pending");
  return hasRunningCell && !hasAssistantMarkdownCell(cells);
}

function hasAssistantMarkdownCell(cells: CodexTranscriptCell[]) {
  return cells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim()));
}

function isUserTextPart(part: AgentMessagePart): part is AgentTextPart {
  return part.type === "text" && part.channel === "user";
}

function isAssistantAnswerTextPart(part: AgentMessagePart): part is AgentTextPart {
  return part.type === "text" && part.channel === "answer";
}

function normalizeCellStatus(status: string | undefined): CodexTranscriptCellStatus {
  const normalized = String(status ?? "").trim().toLowerCase();
  if (["failed", "error", "failure", "timeout", "timed_out", "cancelled"].includes(normalized)) {
    return "failed";
  }
  if (["degraded", "fallback", "partial", "recovered", "unavailable"].includes(normalized)) {
    return "degraded";
  }
  if (["queued", "pending"].includes(normalized)) {
    return "pending";
  }
  if (["running", "thinking", "tooling", "answering", "streaming"].includes(normalized)) {
    return "running";
  }
  return "completed";
}

function cellTone(status: CodexTranscriptCellStatus): CodexTranscriptCellTone {
  if (status === "failed") {
    return "error";
  }
  if (status === "degraded") {
    return "warning";
  }
  if (status === "running" || status === "pending") {
    return "running";
  }
  return "neutral";
}

function compactText(value: string | undefined) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}
