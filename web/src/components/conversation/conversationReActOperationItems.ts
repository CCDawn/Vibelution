import type {
  AgentMessageOperation,
  AgentMessageReActOperationGroup,
} from "./agentMessageOperations";
import { reActGroupTone } from "./conversationOperationState";

export type ReActThoughtItem = {
  id: string;
  value: string;
};

export type ReActResultItem = {
  id: string;
  label: string;
  value: string;
  tone: "default" | "failed";
};

export type ReActResultItemFormatters = {
  operationLabel: (operation: AgentMessageOperation) => string;
  readableOperationResult: (operation: AgentMessageOperation) => string;
};

export function reActGroupDurationLabel(
  group: AgentMessageReActOperationGroup,
  formatDuration: (seconds: number) => string,
) {
  const durations = group.operations
    .map((operation) => operation.durationSeconds)
    .filter((duration): duration is number => typeof duration === "number" && Number.isFinite(duration) && duration > 0);
  if (durations.length === 0) {
    return "";
  }
  return formatDuration(durations.reduce((total, duration) => total + duration, 0));
}

export function reActActionOperations(group: AgentMessageReActOperationGroup) {
  return group.operations.filter((operation) => operation.kind === "tool");
}

export function reActThoughtItems(group: AgentMessageReActOperationGroup): ReActThoughtItem[] {
  const seen = new Set<string>();
  return group.operations
    .filter((operation) => operation.kind === "thought")
    .map((operation) => {
      const value = String(operation.resultPreview || operation.summary || "").trim();
      if (!value || seen.has(value)) {
        return null;
      }
      seen.add(value);
      return {
        id: `${operation.id}-thought`,
        value,
      };
    })
    .filter((item): item is ReActThoughtItem => item !== null);
}

export function reActResultItems(
  group: AgentMessageReActOperationGroup,
  formatters: ReActResultItemFormatters,
): ReActResultItem[] {
  return group.operations
    .filter((operation) => operation.kind === "tool" || (operation.kind === "status" && Boolean(operation.error?.trim())))
    .map((operation) => {
      const error = operation.error?.trim();
      if (error) {
        return {
          id: `${operation.id}-error`,
          label: formatters.operationLabel(operation),
          value: error,
          tone: "failed" as const,
        };
      }
      const result = formatters.readableOperationResult(operation);
      if (!result || result === operation.summary.trim() || operation.kind === "status") {
        return null;
      }
      return {
        id: `${operation.id}-result`,
        label: formatters.operationLabel(operation),
        value: result,
        tone: "default" as const,
      };
    })
    .filter((item): item is ReActResultItem => item !== null);
}

export function shouldExpandReActGroupByDefault(group: AgentMessageReActOperationGroup) {
  const tone = reActGroupTone(group);
  return tone === "running" || tone === "failed" || tone === "pending";
}
