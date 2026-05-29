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
  arguments?: Record<string, unknown>;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number;
  error?: string;
  timeoutSeconds?: number;
  tracePath?: string;
};

export type ConversationOperationLabels = {
  thought: string;
  mental: string;
};

export type ConversationOperationGroups = {
  thoughts: ConversationOperation[];
  mental: ConversationOperation[];
  tools: ConversationOperation[];
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
    const thought = message.thought?.trim() ?? "";
    operations.push({
      id: `${message.id}-thought`,
      kind: "thought",
      label: labels.thought,
      status: resolvedStatus,
      summary: compactPreview(thought),
      durationSeconds: null,
      resultPreview: thought,
    });
  }

  if (hasMentalBlock(message)) {
    operations.push({
      id: `${message.id}-mental`,
      kind: "mental",
      label: labels.mental,
      status: resolvedStatus,
      summary: mentalSnapshotSummary(message.mentalSnapshot),
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
        arguments: toolCall.arguments,
        resultPreview: toolCall.resultPreview,
        resultType: toolCall.resultType,
        resultLength: numberOrNull(toolCall.resultLength) ?? undefined,
        error: toolCall.error,
        timeoutSeconds: numberOrNull(toolCall.timeoutSeconds) ?? undefined,
        tracePath: toolCall.tracePath,
      });
    });
  }

  return operations;
}

export function buildConversationOperationGroups(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
): ConversationOperationGroups {
  const operations = buildConversationOperations(message, labels);
  return {
    thoughts: operations.filter((operation) => operation.kind === "thought"),
    mental: operations.filter((operation) => operation.kind === "mental"),
    tools: operations.filter((operation) => operation.kind === "tool"),
  };
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

function mentalSnapshotSummary(snapshot: ConversationMessage["mentalSnapshot"]) {
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
    .map((item) => String(item ?? "").trim())
    .find(Boolean) ?? "";
}

function compactPreview(value: string, maxLength = 180) {
  const normalized = String(value ?? "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength - 1).trimEnd()}...`;
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
