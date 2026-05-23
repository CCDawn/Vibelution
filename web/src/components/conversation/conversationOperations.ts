import { ConversationMessage, ToolCall } from "../../api/types";
import { hasMentalBlock, hasThoughtBlock, hasToolBlock } from "./messageSections";

export type ConversationOperationKind = "thought" | "mental" | "tool";

export type ConversationOperation = {
  id: string;
  kind: ConversationOperationKind;
  label: string;
  status: string;
  summary: string;
  durationSeconds: number | null;
};

export type ConversationOperationLabels = {
  thought: string;
  mental: string;
};

export function buildConversationOperations(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
): ConversationOperation[] {
  if (message.role !== "assistant") {
    return [];
  }

  const operations: ConversationOperation[] = [];
  const resolvedStatus = message.streaming ? "running" : "done";

  if (hasThoughtBlock(message)) {
    operations.push({
      id: `${message.id}-thought`,
      kind: "thought",
      label: labels.thought,
      status: resolvedStatus,
      summary: "",
      durationSeconds: null,
    });
  }

  if (hasMentalBlock(message)) {
    operations.push({
      id: `${message.id}-mental`,
      kind: "mental",
      label: labels.mental,
      status: resolvedStatus,
      summary: "",
      durationSeconds: null,
    });
  }

  if (hasToolBlock(message)) {
    message.toolCalls?.forEach((toolCall, index) => {
      operations.push({
        id: `${message.id}-tool-${index}`,
        kind: "tool",
        label: toolCall.name,
        status: toolCall.status || "done",
        summary: toolCall.summary?.trim() ?? "",
        durationSeconds: coerceToolDurationSeconds(toolCall),
      });
    });
  }

  return operations;
}

function coerceToolDurationSeconds(toolCall: ToolCall) {
  const value = toolCall as ToolCall & {
    durationSeconds?: unknown;
    elapsedSeconds?: unknown;
    durationMs?: unknown;
  };
  const seconds = numberOrNull(value.durationSeconds ?? value.elapsedSeconds);
  if (seconds !== null) {
    return seconds;
  }
  const durationMs = numberOrNull(value.durationMs);
  return durationMs === null ? null : durationMs / 1000;
}

function numberOrNull(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}
