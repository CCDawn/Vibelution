import { ConversationMessage } from "../../api/types";
import { ConversationOperation } from "./conversationOperations";

export type ConversationTimelineItemStatus = "pending" | "running" | "completed" | "failed";

export type ConversationThoughtTimelineItem = {
  id: string;
  kind: "thought";
  status: ConversationTimelineItemStatus;
  text: string;
  preview: string;
  defaultExpanded: boolean;
  sourceOperationIds: string[];
};

export type ConversationAssistantTextTimelineItem = {
  id: string;
  kind: "assistant_text";
  status: ConversationTimelineItemStatus;
  text: string;
};

export type ConversationOperationTimelineItem = {
  id: string;
  kind: "operation";
  status: ConversationTimelineItemStatus;
  title: string;
  summary: string;
  operation: ConversationOperation;
};

export type ConversationCommandGroupTimelineItem = {
  id: string;
  kind: "command_group";
  status: ConversationTimelineItemStatus;
  title: string;
  summary: string;
  operations: ConversationOperation[];
};

export type ConversationTimelineItem =
  | ConversationThoughtTimelineItem
  | ConversationAssistantTextTimelineItem
  | ConversationOperationTimelineItem
  | ConversationCommandGroupTimelineItem;

export type ConversationTimelineOptions = {
  lang: "zh" | "en" | string;
  includeAssistantText?: boolean;
};

export function buildConversationTimelineItems(
  message: ConversationMessage,
  operations: ConversationOperation[],
  options: ConversationTimelineOptions,
): ConversationTimelineItem[] {
  if (message.role !== "assistant") {
    return [];
  }
  const items: ConversationTimelineItem[] = [];
  const sortedOperations = [...operations].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0));
  const commandBuffer: ConversationOperation[] = [];

  const flushCommandBuffer = () => {
    if (commandBuffer.length === 0) {
      return;
    }
    if (commandBuffer.length === 1) {
      const operation = commandBuffer[0];
      items.push(operationTimelineItem(operation));
    } else {
      items.push(commandGroupTimelineItem(message.id, commandBuffer, options.lang));
    }
    commandBuffer.length = 0;
  };

  for (const operation of sortedOperations) {
    if (operation.kind === "thought") {
      flushCommandBuffer();
      const text = operationText(operation);
      if (text) {
        items.push({
          id: `${operation.id}-timeline-thought`,
          kind: "thought",
          status: normalizeTimelineStatus(operation.status),
          text,
          preview: firstParagraphPreview(text),
          defaultExpanded: isRunningStatus(operation.status),
          sourceOperationIds: [operation.id],
        });
      }
      continue;
    }
    if (operation.kind === "mental") {
      continue;
    }
    if (isCommandLikeOperation(operation)) {
      commandBuffer.push(operation);
      continue;
    }
    flushCommandBuffer();
    if (operation.kind === "status" && !operation.error?.trim() && normalizeTimelineStatus(operation.status) !== "failed") {
      continue;
    }
    items.push(operationTimelineItem(operation));
  }
  flushCommandBuffer();

  if (options.includeAssistantText !== false) {
    const text = String(message.content ?? "").trim();
    if (text) {
      items.push({
        id: `${message.id}-timeline-response`,
        kind: "assistant_text",
        status: message.streaming ? "running" : "completed",
        text,
      });
    }
  }

  return mergeAdjacentThoughtItems(items);
}

function operationTimelineItem(operation: ConversationOperation): ConversationOperationTimelineItem {
  return {
    id: `${operation.id}-timeline-operation`,
    kind: "operation",
    status: normalizeTimelineStatus(operation.status),
    title: operation.label,
    summary: operation.summary,
    operation,
  };
}

function commandGroupTimelineItem(
  messageId: string,
  operations: ConversationOperation[],
  lang: string,
): ConversationCommandGroupTimelineItem {
  const status = operations.some((operation) => isFailedStatus(operation.status))
    ? "failed"
    : operations.some((operation) => isRunningStatus(operation.status))
      ? "running"
      : "completed";
  const commandCount = operations.length;
  const title = lang === "zh"
    ? status === "running"
      ? `正在运行 ${commandCount} 条命令`
      : `已运行 ${commandCount} 条命令`
    : status === "running"
      ? `Running ${commandCount} commands`
      : `Ran ${commandCount} commands`;
  const summary = operations
    .map((operation) => operation.summary || operation.label)
    .filter(Boolean)
    .slice(0, 2)
    .join("；");
  const first = operations[0];
  const last = operations[operations.length - 1];
  return {
    id: `${messageId}-timeline-command-group-${first.sequence ?? first.id}-${last.sequence ?? last.id}`,
    kind: "command_group",
    status,
    title,
    summary,
    operations: [...operations],
  };
}

function mergeAdjacentThoughtItems(items: ConversationTimelineItem[]) {
  const merged: ConversationTimelineItem[] = [];
  for (const item of items) {
    const previous = merged[merged.length - 1];
    if (previous?.kind === "thought" && item.kind === "thought") {
      const text = appendNaturalText(previous.text, item.text);
      merged[merged.length - 1] = {
        ...previous,
        status: item.status === "running" ? "running" : previous.status,
        text,
        preview: firstParagraphPreview(text),
        defaultExpanded: previous.defaultExpanded || item.defaultExpanded,
        sourceOperationIds: [...previous.sourceOperationIds, ...item.sourceOperationIds],
      };
      continue;
    }
    merged.push(item);
  }
  return merged;
}

function operationText(operation: ConversationOperation) {
  return String(operation.resultPreview || operation.summary || "").trim();
}

function appendNaturalText(previous: string, next: string) {
  const left = previous.trimEnd();
  const right = next.trimStart();
  if (!left) {
    return right;
  }
  if (!right) {
    return left;
  }
  if (left.endsWith(right)) {
    return left;
  }
  return `${left}\n\n${right}`;
}

function firstParagraphPreview(text: string) {
  const paragraph = String(text || "")
    .split(/\n\s*\n/)
    .map((item) => item.trim())
    .find(Boolean) ?? "";
  return paragraph.length > 180 ? `${paragraph.slice(0, 180).trimEnd()}...` : paragraph;
}

function isCommandLikeOperation(operation: ConversationOperation) {
  if (operation.kind !== "tool") {
    return false;
  }
  const haystack = [
    operation.rawLabel,
    operation.label,
    operation.summary,
  ].map((item) => String(item ?? "").toLowerCase()).join(" ");
  if ([
    "apply_diff",
    "edit",
    "编辑",
    "computer_use",
    "image",
    "spawn_agent",
    "cli_agent",
  ].some((marker) => haystack.includes(marker))) {
    return false;
  }
  return [
    "tool_",
    "cli_tool",
    "shell",
    "command",
    "命令",
    "grep_search_tool",
    "read_file_tool",
    "glob_tool",
    "rg",
    "搜索",
    "读取",
    "列出",
  ].some((marker) => haystack.includes(marker));
}

function normalizeTimelineStatus(status: string | undefined): ConversationTimelineItemStatus {
  if (isFailedStatus(status)) {
    return "failed";
  }
  if (isRunningStatus(status)) {
    return "running";
  }
  if (["queued", "pending"].includes(String(status ?? "").trim().toLowerCase())) {
    return "pending";
  }
  return "completed";
}

function isRunningStatus(status: string | undefined) {
  return ["running", "thinking", "tooling", "answering", "streaming", "pending"].includes(
    String(status ?? "").trim().toLowerCase(),
  );
}

function isFailedStatus(status: string | undefined) {
  return ["failed", "error", "timeout", "cancelled"].includes(String(status ?? "").trim().toLowerCase());
}
