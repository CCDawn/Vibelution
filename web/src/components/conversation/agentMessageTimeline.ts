import type { AgentMessage, AgentMessagePart, AgentTextPart } from "../../agent-thread/types";
import { AgentMessageOperation } from "./agentMessageOperations";

export type AgentMessageTimelineItemStatus = "pending" | "running" | "completed" | "failed";

export type AgentMessageThoughtTimelineItem = {
  id: string;
  kind: "thought";
  status: AgentMessageTimelineItemStatus;
  text: string;
  preview: string;
  defaultExpanded: boolean;
  sourceOperationIds: string[];
};

export type AgentMessageAssistantTextTimelineItem = {
  id: string;
  kind: "assistant_text";
  status: AgentMessageTimelineItemStatus;
  text: string;
};

export type AgentMessageOperationTimelineItem = {
  id: string;
  kind: "operation";
  status: AgentMessageTimelineItemStatus;
  title: string;
  summary: string;
  operation: AgentMessageOperation;
};

export type AgentMessageCommandGroupTimelineItem = {
  id: string;
  kind: "command_group";
  status: AgentMessageTimelineItemStatus;
  title: string;
  summary: string;
  operations: AgentMessageOperation[];
};

export type AgentMessageTimelineItem =
  | AgentMessageThoughtTimelineItem
  | AgentMessageAssistantTextTimelineItem
  | AgentMessageOperationTimelineItem
  | AgentMessageCommandGroupTimelineItem;

export type AgentMessageTimelineOptions = {
  lang: "zh" | "en" | string;
  includeAssistantText?: boolean;
};

export type AgentMessageTimelineServerItem = {
  id: string;
  turnId?: string;
  messageId?: string;
  sequence?: number;
  kind: "thought" | "assistant_text" | "operation" | "command_group" | string;
  status?: "pending" | "running" | "completed" | "failed" | string;
  title?: string;
  summary?: string;
  text?: string;
  preview?: string;
  defaultExpanded?: boolean;
  sourceOperationIds?: string[];
  operationIds?: string[];
  metadata?: Record<string, unknown>;
};

const agentTimelineItemsCache = new WeakMap<
  AgentMessage,
  {
    operations: AgentMessageOperation[];
    serverItems: AgentMessageTimelineServerItem[] | undefined;
    lang: string;
    includeAssistantText: boolean | undefined;
    items: AgentMessageTimelineItem[];
  }
>();

export function buildAgentMessageTimelineItems(
  message: AgentMessage,
  operations: AgentMessageOperation[],
  options: AgentMessageTimelineOptions,
  serverItems?: AgentMessageTimelineServerItem[],
): AgentMessageTimelineItem[] {
  if (message.role !== "assistant") {
    return [];
  }
  const cached = agentTimelineItemsCache.get(message);
  if (
    cached
    && cached.operations === operations
    && cached.serverItems === serverItems
    && cached.lang === options.lang
    && cached.includeAssistantText === options.includeAssistantText
  ) {
    return cached.items;
  }
  const items = buildAgentMessageTimelineItemsUncached(message, operations, options, serverItems);
  agentTimelineItemsCache.set(message, {
    operations,
    serverItems,
    lang: options.lang,
    includeAssistantText: options.includeAssistantText,
    items,
  });
  return items;
}

function buildAgentMessageTimelineItemsUncached(
  message: AgentMessage,
  operations: AgentMessageOperation[],
  options: AgentMessageTimelineOptions,
  serverItems?: AgentMessageTimelineServerItem[],
): AgentMessageTimelineItem[] {
  if ((serverItems?.length ?? 0) > 0) {
    return timelineItemsFromServer(serverItems ?? [], operations, options);
  }
  return timelineItemsFromOperations(
    message.id,
    Boolean(message.streaming),
    agentMessageAnswerText(message),
    operations,
    options,
  );
}

function timelineItemsFromOperations(
  messageId: string,
  messageStreaming: boolean,
  assistantText: string,
  operations: AgentMessageOperation[],
  options: AgentMessageTimelineOptions,
): AgentMessageTimelineItem[] {
  const items: AgentMessageTimelineItem[] = [];
  const sortedOperations = [...operations].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0));

  for (const operation of sortedOperations) {
    if (operation.kind === "thought") {
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
    if (operation.kind === "status" && !operation.error?.trim() && normalizeTimelineStatus(operation.status) !== "failed") {
      continue;
    }
    items.push(operationTimelineItem(operation));
  }

  if (options.includeAssistantText !== false) {
    const text = assistantText.trim();
    if (text) {
      items.push({
        id: `${messageId}-timeline-response`,
        kind: "assistant_text",
        status: messageStreaming ? "running" : "completed",
        text,
      });
    }
  }

  return mergeAdjacentThoughtItems(items);
}

function agentMessageAnswerText(message: AgentMessage) {
  return message.parts
    .filter(isAgentAnswerTextPart)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
}

function isAgentAnswerTextPart(part: AgentMessagePart): part is AgentTextPart {
  return part.type === "text" && part.channel === "answer";
}

function timelineItemsFromServer(
  serverItems: AgentMessageTimelineServerItem[],
  operations: AgentMessageOperation[],
  options: AgentMessageTimelineOptions,
): AgentMessageTimelineItem[] {
  const operationsById = new Map(operations.map((operation) => [operation.id, operation]));
  const items: AgentMessageTimelineItem[] = [];
  for (const item of serverItems) {
    const kind = String(item.kind || "").trim();
    const status = normalizeTimelineStatus(item.status);
    if (kind === "thought") {
      const text = String(item.text || item.preview || item.summary || "").trim();
      if (!text) {
        continue;
      }
      items.push({
        id: item.id || `timeline-thought-${items.length + 1}`,
        kind: "thought",
        status,
        text,
        preview: String(item.preview || firstParagraphPreview(text)).trim(),
        defaultExpanded: Boolean(item.defaultExpanded) || status === "running",
        sourceOperationIds: [...(item.sourceOperationIds || item.operationIds || [])],
      });
      continue;
    }
    if (kind === "assistant_text") {
      if (options.includeAssistantText === false) {
        continue;
      }
      const text = String(item.text || "").trim();
      if (text) {
        items.push({
          id: item.id || `timeline-response-${items.length + 1}`,
          kind: "assistant_text",
          status,
          text,
        });
      }
      continue;
    }
    if (kind === "command_group") {
      const commandOperations = (item.operationIds || item.sourceOperationIds || [])
        .map((operationId) => operationsById.get(operationId))
        .filter((operation): operation is AgentMessageOperation => Boolean(operation));
      items.push({
        id: item.id || `timeline-command-group-${items.length + 1}`,
        kind: "command_group",
        status,
        title: String(item.title || commandGroupTitle(commandOperations, status, options.lang)).trim(),
        summary: String(item.summary || commandOperations.slice(0, 2).map((operation) => operation.summary || operation.label).filter(Boolean).join("；")).trim(),
        operations: commandOperations,
      });
      continue;
    }
    if (kind === "operation") {
      const operation = (item.operationIds || item.sourceOperationIds || [])
        .map((operationId) => operationsById.get(operationId))
        .find(Boolean) ?? serverOperation(item, status);
      items.push({
        id: item.id || `${operation.id}-timeline-operation`,
        kind: "operation",
        status,
        title: String(item.title || operation.label).trim(),
        summary: String(item.summary || operation.summary || "").trim(),
        operation,
      });
    }
  }
  return mergeAdjacentThoughtItems(items);
}

function serverOperation(
  item: AgentMessageTimelineServerItem,
  status: AgentMessageTimelineItemStatus,
): AgentMessageOperation {
  return {
    id: item.id || `server-operation-${item.sequence ?? "unknown"}`,
    kind: "status",
    label: String(item.title || "运行状态"),
    status: status === "completed" ? "done" : status,
    summary: String(item.summary || item.preview || "").trim(),
    durationSeconds: null,
  };
}

function operationTimelineItem(operation: AgentMessageOperation): AgentMessageOperationTimelineItem {
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
  operations: AgentMessageOperation[],
  lang: string,
): AgentMessageCommandGroupTimelineItem {
  const status = operations.some((operation) => isFailedStatus(operation.status))
    ? "failed"
    : operations.some((operation) => isRunningStatus(operation.status))
      ? "running"
      : "completed";
  const commandCount = operations.length;
  const title = commandGroupTitle(operations, status, lang);
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

function commandGroupTitle(
  operations: AgentMessageOperation[],
  status: AgentMessageTimelineItemStatus,
  lang: string,
) {
  const commandCount = operations.length;
  if (lang === "zh") {
    return status === "running" ? `正在运行 ${commandCount} 条命令` : `已运行 ${commandCount} 条命令`;
  }
  return status === "running" ? `Running ${commandCount} commands` : `Ran ${commandCount} commands`;
}

function mergeAdjacentThoughtItems(items: AgentMessageTimelineItem[]) {
  const merged: AgentMessageTimelineItem[] = [];
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

function operationText(operation: AgentMessageOperation) {
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

function isCommandLikeOperation(operation: AgentMessageOperation) {
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

function normalizeTimelineStatus(status: string | undefined): AgentMessageTimelineItemStatus {
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
