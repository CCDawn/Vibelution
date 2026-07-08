import type { AgentMessage, AgentMessagePart, AgentTextPart } from "../../agent-thread/types";
import { AgentMessageOperation } from "./agentMessageOperations";
import { shouldDisplayRuntimeStatus } from "./conversationDisplayProtocol";
import { compactVisibleTimelineOperations } from "./conversationOperationState";

export type AgentMessageTimelineItemStatus = "pending" | "running" | "completed" | "failed" | "degraded";

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
    return timelineItemsFromServer(serverItems ?? [], operations, options, message);
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
  const sortedOperations = compactVisibleTimelineOperations(
    [...operations].sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0)),
  );

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
    if (!shouldDisplayTimelineOperation(operation)) {
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
  message?: AgentMessage,
): AgentMessageTimelineItem[] {
  const operationsById = operationsByTimelineId(operations, message);
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
      const requestedOperationIds = item.operationIds || item.sourceOperationIds || [];
      const commandOperations = (item.operationIds || item.sourceOperationIds || [])
        .map((operationId) => operationsById.get(operationId))
        .filter((operation): operation is AgentMessageOperation => Boolean(operation));
      if (commandOperations.length > 0) {
        items.push(serverCommandGroupTimelineItem(item, commandOperations, status, options.lang));
        continue;
      }
      items.push(missingCommandGroupOperation(item, requestedOperationIds, options.lang));
      continue;
    }
    if (kind === "operation") {
      const operation = (item.operationIds || item.sourceOperationIds || [])
        .map((operationId) => operationsById.get(operationId))
        .find(Boolean) ?? serverOperation(item, status);
      const timelineOperation = operationWithServerTimelineStatus(operation, status);
      if (!shouldDisplayTimelineOperation(timelineOperation, item)) {
        continue;
      }
      items.push({
        id: item.id || `${timelineOperation.id}-timeline-operation`,
        kind: "operation",
        status,
        title: String(item.title || timelineOperation.label).trim(),
        summary: String(item.summary || timelineOperation.summary || "").trim(),
        operation: timelineOperation,
      });
    }
  }
  return mergeAdjacentThoughtItems(items);
}

function shouldDisplayTimelineOperation(
  operation: AgentMessageOperation,
  item?: AgentMessageTimelineServerItem,
) {
  return shouldDisplayRuntimeStatus({
    kind: operation.kind,
    name: item?.title ?? operation.label,
    status: item?.status ?? operation.status,
    summary: item?.summary ?? operation.summary,
    resultPreview: operation.resultPreview,
    error: operation.error,
  });
}

function operationWithServerTimelineStatus(
  operation: AgentMessageOperation,
  status: AgentMessageTimelineItemStatus,
): AgentMessageOperation {
  const operationStatus = serverTimelineOperationStatus(status);
  if (operation.status === operationStatus) {
    return operation;
  }
  return {
    ...operation,
    status: operationStatus,
    rawStatus: operation.rawStatus ?? operation.status,
  };
}

function serverTimelineOperationStatus(status: AgentMessageTimelineItemStatus) {
  return status === "completed" ? "done" : status;
}

function operationsByTimelineId(
  operations: AgentMessageOperation[],
  message?: AgentMessage,
) {
  const operationsById = new Map(operations.map((operation) => [operation.id, operation]));
  const projectedMessageIds = projectedMessageIdsForOperationAliases(message);
  if (projectedMessageIds.length === 0) {
    return operationsById;
  }
  for (const operation of operations) {
    if (typeof operation.sequence !== "number" || operation.sequence <= 0) {
      continue;
    }
    for (const messageId of projectedMessageIds) {
      operationsById.set(`${messageId}-feedback-${operation.sequence}`, operation);
    }
  }
  return operationsById;
}

function projectedMessageIdsForOperationAliases(message?: AgentMessage) {
  const projected = message?.metadata?.projectedMessageIds ?? message?.source.metadata?.projectedMessageIds;
  if (!Array.isArray(projected)) {
    return [];
  }
  return projected.map((item) => String(item).trim()).filter(Boolean);
}

function missingCommandGroupOperation(
  item: AgentMessageTimelineServerItem,
  requestedOperationIds: string[],
  lang: string,
): AgentMessageOperationTimelineItem {
  const groupId = item.id || "timeline-command-group";
  const count = requestedOperationIds.length;
  const title = lang === "zh" ? "工具调用投影缺失" : "Tool call projection missing";
  const summary = lang === "zh"
    ? `${groupId} 引用了 ${count} 条工具结果，但当前消息没有匹配的 operation 投影。`
    : `${groupId} references ${count} tool results, but the current message has no matching operation projection.`;
  const detail = String(item.summary || item.title || "").trim();
  const operation: AgentMessageOperation = {
    id: `${groupId}-missing-operation-projection`,
    kind: "status",
    label: title,
    status: "failed",
    summary,
    durationSeconds: null,
    resultPreview: detail || summary,
  };
  return {
    id: `${operation.id}-timeline-operation`,
    kind: "operation",
    status: "failed",
    title,
    summary,
    operation,
  };
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

function serverCommandGroupTimelineItem(
  item: AgentMessageTimelineServerItem,
  operations: AgentMessageOperation[],
  status: AgentMessageTimelineItemStatus,
  lang: string,
): AgentMessageCommandGroupTimelineItem {
  const inferred = commandGroupTimelineItem(item.messageId || item.turnId || item.id || "server-command-group", operations, lang);
  const title = String(item.title || inferred.title).trim();
  const summary = String(item.summary || inferred.summary).trim();
  return {
    id: item.id || inferred.id,
    kind: "command_group",
    status: strongestCommandGroupStatus(status, operations),
    title,
    summary,
    operations: [...operations],
  };
}

function strongestCommandGroupStatus(
  serverStatus: AgentMessageTimelineItemStatus,
  operations: AgentMessageOperation[],
): AgentMessageTimelineItemStatus {
  if (serverStatus === "failed" || operations.some((operation) => isFailedStatus(operation.status))) {
    return "failed";
  }
  if (serverStatus === "degraded" || operations.some((operation) => isDegradedStatus(operation.status))) {
    return "degraded";
  }
  if (serverStatus === "running" || operations.some((operation) => isRunningStatus(operation.status))) {
    return "running";
  }
  if (serverStatus === "pending") {
    return "pending";
  }
  return "completed";
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
  const allShellCommands = operations.length > 0 && operations.every(isShellCommandOperation);
  if (lang === "zh") {
    if (allShellCommands) {
      return status === "running" ? `正在运行 ${commandCount} 条命令` : `已运行 ${commandCount} 条命令`;
    }
    return status === "running" ? `正在执行 ${commandCount} 项工具` : `已执行 ${commandCount} 项工具`;
  }
  if (allShellCommands) {
    return status === "running" ? `Running ${commandCount} commands` : `Ran ${commandCount} commands`;
  }
  return status === "running" ? `Running ${commandCount} tools` : `Ran ${commandCount} tools`;
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

function isShellCommandOperation(operation: AgentMessageOperation) {
  if (operation.kind !== "tool") {
    return false;
  }
  const rawName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  if (["cli_tool", "shell_tool", "command_tool", "execute_shell_command"].includes(rawName)) {
    return true;
  }
  const haystack = [
    operation.rawLabel,
    operation.label,
    operation.summary,
  ].map((item) => String(item ?? "").toLowerCase()).join(" ");
  if ([
    "grep_search_tool",
    "read_file_tool",
    "glob_tool",
    "code_symbol_tool",
    "search",
    "read",
    "glob",
    "搜索",
    "读取",
    "列出",
    "代码图谱",
  ].some((marker) => haystack.includes(marker))) {
    return false;
  }
  return ["shell", "command", "命令"].some((marker) => haystack.includes(marker));
}

function normalizeTimelineStatus(status: string | undefined): AgentMessageTimelineItemStatus {
  if (isFailedStatus(status)) {
    return "failed";
  }
  if (isDegradedStatus(status)) {
    return "degraded";
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

function isDegradedStatus(status: string | undefined) {
  return ["degraded", "fallback", "partial", "recovered", "unavailable"].includes(
    String(status ?? "").trim().toLowerCase(),
  );
}
