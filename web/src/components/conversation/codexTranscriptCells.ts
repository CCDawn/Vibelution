import type { AgentMessage, AgentMessagePart, AgentTextPart } from "../../agent-thread/types";
import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageTimelineItem, AgentMessageTimelineItemStatus } from "./agentMessageTimeline";
import { buildCodexRolloutTraceEvents, type CodexRolloutTraceEvent } from "./codexRolloutTrace";
import { buildCodexToolLifecycleModel, type CodexToolLifecycleModel } from "./codexToolLifecycleModel";

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

  const cells = options.timelineItems?.length
    ? cellsFromTimelineItems(message.id, options.timelineItems)
    : cellsFromOperations(message.id, options.operations ?? []);
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
    summary: status === "failed"
      ? compactText(operation.error || timelineSummary || operation.summary)
      : compactText(timelineSummary || operation.summary),
    operationIds: [operation.id],
    toolLifecycleModel: operation.kind === "tool" ? buildCodexToolLifecycleModel(operation) : undefined,
    rolloutTraceEvents: buildCodexRolloutTraceEvents(operation),
    sourceItemId,
  };
}

function answerTextFromMessage(message: AgentMessage) {
  return message.parts
    .filter(isAssistantAnswerTextPart)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
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
