import { ConversationFeedbackEvent, ConversationMessage, ToolCall } from "../../api/types";
import { hasMentalBlock, hasThoughtBlock, hasToolBlock } from "./messageSections";

export type ConversationOperationKind = "thought" | "mental" | "tool" | "status";

export type ConversationOperation = {
  id: string;
  kind: ConversationOperationKind;
  label: string;
  rawLabel?: string;
  status: string;
  rawStatus?: string;
  summary: string;
  durationSeconds: number | null;
  arguments?: Record<string, unknown>;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number;
  error?: string;
  timeoutSeconds?: number;
  tracePath?: string;
  sequence?: number;
  timestamp?: string;
  relatedThoughtSequence?: number;
};

export type ConversationOperationLabels = {
  thought: string;
  mental: string;
  status: string;
};

export type ConversationOperationGroups = {
  timeline: ConversationOperation[];
  thoughts: ConversationOperation[];
  mental: ConversationOperation[];
  status: ConversationOperation[];
  tools: ConversationOperation[];
};

export type ConversationReActOperationGroup = {
  id: string;
  index: number;
  operations: ConversationOperation[];
  thoughtSequence?: number;
};

const FEEDBACK_OPERATION_CACHE_LIMIT = 200;
const feedbackOperationCache = new Map<string, ConversationOperation[]>();

export function buildConversationOperations(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
): ConversationOperation[] {
  if (message.role !== "assistant") {
    return [];
  }

  const operations: ConversationOperation[] = [];
  const resolvedStatus = message.streaming ? "running" : "done";

  if ((message.feedbackEvents?.length ?? 0) > 0) {
    const cacheKey = feedbackOperationCacheKey(message, labels, resolvedStatus);
    const cached = feedbackOperationCache.get(cacheKey);
    if (cached) {
      return cached;
    }
    const operations = buildOperationsFromFeedbackEvents(message, labels, resolvedStatus);
    feedbackOperationCache.set(cacheKey, operations);
    if (feedbackOperationCache.size > FEEDBACK_OPERATION_CACHE_LIMIT) {
      const oldestCacheKey = feedbackOperationCache.keys().next().value;
      if (oldestCacheKey) {
        feedbackOperationCache.delete(oldestCacheKey);
      }
    }
    return operations;
  }

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

function feedbackOperationCacheKey(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
  resolvedStatus: string,
) {
  const events = message.feedbackEvents ?? [];
  const eventsFingerprint = events.map((event) => [
    event.sequence ?? "",
    event.timestamp ?? "",
    event.kind ?? "",
    event.status ?? "",
    event.name ?? "",
    event.summary ?? "",
    event.resultPreview ?? "",
    event.error ?? "",
  ].join(":")).join(";");
  return [
    message.id,
    message.streaming ? "streaming" : "done",
    resolvedStatus,
    labels.thought,
    labels.mental,
    labels.status,
    events.length,
    eventsFingerprint,
  ].join("|");
}

export function buildConversationOperationGroups(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
): ConversationOperationGroups {
  const operations = buildConversationOperations(message, labels);
  return {
    timeline: operations,
    thoughts: operations.filter((operation) => operation.kind === "thought"),
    mental: operations.filter((operation) => operation.kind === "mental"),
    status: operations.filter((operation) => operation.kind === "status"),
    tools: operations.filter((operation) => operation.kind === "tool"),
  };
}

export function buildConversationReActOperationGroups(
  operations: ConversationOperation[],
): ConversationReActOperationGroup[] {
  const groups: ConversationReActOperationGroup[] = [];
  let current: ConversationReActOperationGroup | null = null;

  const startGroup = (operation: ConversationOperation) => {
    const group: ConversationReActOperationGroup = {
      id: `react-${groups.length + 1}-${operation.id}`,
      index: groups.length + 1,
      operations: [],
      thoughtSequence: operation.kind === "thought" ? operation.sequence : undefined,
    };
    groups.push(group);
    current = group;
    return group;
  };

  for (const operation of operations) {
    let target: ConversationReActOperationGroup | null = current;
    if (!target) {
      target = startGroup(operation);
    } else if (operation.kind === "thought" && reactGroupHasThought(target)) {
      target = startGroup(operation);
    }
    if (!target) {
      continue;
    }

    target.operations.push(operation);
    if (operation.kind === "thought" && target.thoughtSequence === undefined) {
      target.thoughtSequence = operation.sequence;
    }
  }

  return groups.map((group) => ({
    ...group,
    id: stableReActGroupId(group),
  }));
}

function reactGroupHasThought(group: ConversationReActOperationGroup) {
  return group.operations.some((operation) => operation.kind === "thought");
}

function stableReActGroupId(group: ConversationReActOperationGroup) {
  const relatedThoughtSequence = group.operations
    .map((operation) => operation.relatedThoughtSequence)
    .find((sequence): sequence is number => typeof sequence === "number" && sequence > 0);
  const thoughtSequence = group.thoughtSequence ?? relatedThoughtSequence;
  if (thoughtSequence && thoughtSequence > 0) {
    return `react-thought-${thoughtSequence}`;
  }
  const firstSequence = group.operations
    .map((operation) => operation.sequence)
    .find((sequence): sequence is number => typeof sequence === "number" && sequence > 0);
  if (firstSequence && firstSequence > 0) {
    return `react-operation-${firstSequence}`;
  }
  return `react-${group.index}-${group.operations[0]?.id ?? "empty"}`;
}

function buildOperationsFromFeedbackEvents(
  message: ConversationMessage,
  labels: ConversationOperationLabels,
  resolvedStatus: string,
) {
  const operations = [...(message.feedbackEvents ?? [])]
    .sort((a, b) => (numberOrNull(a.sequence) ?? 0) - (numberOrNull(b.sequence) ?? 0))
    .map((event, index) => feedbackEventToOperation(message.id, event, index, labels, resolvedStatus))
    .filter((operation): operation is ConversationOperation => operation !== null);
  return normalizeTimelineOperations(operations, Boolean(message.streaming));
}

function feedbackEventToOperation(
  messageId: string,
  event: ConversationFeedbackEvent,
  index: number,
  labels: ConversationOperationLabels,
  resolvedStatus: string,
): ConversationOperation | null {
  const kind = event.kind;
  if (!["thought", "mental", "tool", "status"].includes(kind)) {
    return null;
  }
  const rawLabel = kind === "tool" ? event.name?.trim() || "tool" : undefined;
  const statusDisplay = kind === "status" ? statusOperationDisplay(event, labels.status) : null;
  const label = kind === "thought"
    ? labels.thought
    : kind === "mental"
      ? labels.mental
      : kind === "status"
        ? statusDisplay?.label ?? labels.status
        : displayToolLabel(rawLabel ?? "tool");
  const status = event.status?.trim() || (kind === "tool" ? "done" : resolvedStatus);
  const rawSummary = event.summary?.trim() || event.resultPreview?.trim() || "";
  return {
    id: `${messageId}-feedback-${event.sequence || index + 1}`,
    kind,
    label,
    rawLabel: kind === "status" ? event.name?.trim() || undefined : rawLabel,
    status,
    rawStatus: status,
    summary: compactPreview(statusDisplay?.summary ?? rawSummary),
    durationSeconds: coerceDurationSeconds(event),
    arguments: event.arguments,
    resultPreview: statusDisplay?.detail ?? event.resultPreview,
    resultType: event.resultType,
    resultLength: numberOrNull(event.resultLength) ?? undefined,
    error: event.error,
    timeoutSeconds: numberOrNull(event.timeoutSeconds) ?? undefined,
    tracePath: event.tracePath,
    sequence: numberOrNull(event.sequence) ?? undefined,
    timestamp: event.timestamp,
    relatedThoughtSequence: numberOrNull(event.relatedThoughtSequence) ?? undefined,
  };
}

export function normalizeTimelineOperations(
  operations: ConversationOperation[],
  messageStreaming: boolean,
): ConversationOperation[] {
  const merged: ConversationOperation[] = [];
  for (const operation of operations) {
    const next = normalizeOperationDisplay(operation);
    const previous = merged[merged.length - 1];
    if (previous && previous.kind === "thought" && next.kind === "thought") {
      if (mergeThoughtOperation(merged, merged.length - 1, next)) {
        continue;
      }
    }
    merged.push(next);
  }
  const latestRunningIndex = messageStreaming && isRunningStatus(merged[merged.length - 1]?.status)
    ? merged.length - 1
    : -1;
  const latestProgressIndex = findLatestConcreteProgressIndex(merged);
  return merged.map((operation, index) => {
    if (isSyntheticFailedOperation(operation) && index < latestProgressIndex) {
      return {
        ...operation,
        status: "done",
        rawStatus: operation.rawStatus ?? operation.status,
      };
    }
    if (!isRunningStatus(operation.status)) {
      return operation;
    }
    if (index === latestRunningIndex) {
      return operation;
    }
    return {
      ...operation,
      status: "done",
      rawStatus: operation.rawStatus ?? operation.status,
    };
  });
}

function findLatestConcreteProgressIndex(operations: ConversationOperation[]) {
  for (let index = operations.length - 1; index >= 0; index -= 1) {
    const operation = operations[index];
    if (operation && ["done", "failed"].includes(operation.status)) {
      return index;
    }
  }
  return -1;
}

function isSyntheticFailedOperation(operation: ConversationOperation) {
  if (operation.status !== "failed") {
    return false;
  }
  if (operation.error?.trim()) {
    return false;
  }
  return operation.kind === "status" || operation.kind === "thought" || operation.kind === "mental";
}

function mergeThoughtOperation(
  operations: ConversationOperation[],
  targetIndex: number,
  next: ConversationOperation,
) {
  const previous = operations[targetIndex];
  if (!previous || previous.kind !== "thought" || next.kind !== "thought") {
    return false;
  }
  const previousText = previous.resultPreview || previous.summary;
  const nextText = next.resultPreview || next.summary;
  if (!nextText || nextText === previousText) {
    return true;
  }
  if (!previousText || !nextText.startsWith(previousText)) {
    return false;
  }
  operations[targetIndex] = {
    ...previous,
    ...next,
    id: previous.id,
    sequence: previous.sequence,
    summary: compactPreview(nextText),
    resultPreview: nextText,
    rawStatus: next.rawStatus ?? previous.rawStatus,
  };
  return true;
}

function normalizeOperationDisplay(operation: ConversationOperation): ConversationOperation {
  const rawStatus = operation.rawStatus ?? operation.status;
  return {
    ...operation,
    rawStatus,
    status: normalizeDisplayStatus(operation.status),
    label: operation.kind === "tool" ? displayToolLabel(operation.rawLabel ?? operation.label) : operation.label,
  };
}

function normalizeDisplayStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["done", "success", "completed", "succeeded", "finished", "ready"].includes(normalized)) {
    return "done";
  }
  if (["error", "failed", "failure", "timeout", "timed_out"].includes(normalized)) {
    return "failed";
  }
  if (isRunningStatus(normalized)) {
    return normalized || "running";
  }
  return normalized || "done";
}

function statusOperationDisplay(
  event: ConversationFeedbackEvent,
  fallbackLabel: string,
): { label: string; summary: string; detail: string } {
  const rawName = String(event.name ?? "").trim();
  const rawSummary = String(event.summary ?? event.resultPreview ?? "").trim();
  const key = `${rawName} ${rawSummary}`.toLowerCase();
  const zh = /[\u4e00-\u9fff]/.test(rawSummary || fallbackLabel);
  const label = (() => {
    if (key.includes("context_prepare") || key.includes("准备对话上下文") || key.includes("读取当前会话")) {
      return zh ? "准备上下文" : "Prepare context";
    }
    if (key.includes("agent_prepare") || key.includes("唤起对话 agent") || key.includes("绑定 agent")) {
      return zh ? "绑定 Agent" : "Bind agent";
    }
    if (key.includes("model_request") || key.includes("请求模型") || key.includes("llm 调用")) {
      return zh ? "请求模型" : "Request model";
    }
    if (key.includes("model_thinking") || key.includes("正在思考") || key.includes("reasoning")) {
      return zh ? "模型思考" : "Model thinking";
    }
    if (key.includes("tool") || key.includes("工具")) {
      return zh ? "工具调用" : "Tool call";
    }
    if (key.includes("answer") || key.includes("回答") || key.includes("响应")) {
      return zh ? "生成回答" : "Generate answer";
    }
    return rawName ? compactStatusName(rawName) : fallbackLabel;
  })();
  return {
    label,
    summary: statusOperationSummary(label, rawSummary, zh),
    detail: rawSummary,
  };
}

function statusOperationSummary(label: string, rawSummary: string, zh: boolean) {
  const normalized = rawSummary.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "";
  }
  if (label === "准备上下文" || label === "Prepare context") {
    return zh ? "读取会话、Agent 与工具权限" : "Reading session, agent, and tools";
  }
  if (label === "绑定 Agent" || label === "Bind agent") {
    return zh ? "绑定实例、工作区和记忆根" : "Binding instance, workspace, and memory";
  }
  if (label === "请求模型" || label === "Request model") {
    return zh ? "首个响应片段等待中" : "Waiting for first response chunk";
  }
  if (label === "模型思考" || label === "Model thinking") {
    return zh ? "reasoning 已开始返回" : "Reasoning has started";
  }
  if (label === "工具调用" || label === "Tool call") {
    return zh ? "等待工具结果" : "Waiting for tool result";
  }
  if (label === "生成回答" || label === "Generate answer") {
    return zh ? "正在写入回答正文" : "Writing answer text";
  }
  return compactPreview(normalized, 64);
}

function compactStatusName(name: string) {
  const normalized = name.replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "Runtime status";
  }
  return normalized.replace(/\b\w/g, (char) => char.toUpperCase());
}

function isRunningStatus(status: string) {
  return ["queued", "pending", "running", "thinking", "tooling", "answering"].includes(
    String(status || "").trim().toLowerCase(),
  );
}

export function displayToolLabel(name: string) {
  const normalized = String(name || "").trim();
  const lower = normalized.toLowerCase();
  if (!normalized) {
    return "tool";
  }
  const exact: Record<string, string> = {
    cli_tool: "命令",
    grep_search_tool: "搜索",
    read_file_tool: "读取文件",
    glob_tool: "列出文件",
    code_symbol_tool: "代码图谱",
    get_git_status_summary_tool: "Git 状态",
    image2_generate_tool: "生成图片",
    web_search_tool: "网页搜索",
    web_fetch_tool: "网页读取",
    computer_use_task_tool: "沙盒浏览器",
  };
  if (exact[lower]) {
    return exact[lower];
  }
  if (lower.includes("search")) {
    return "搜索";
  }
  if (lower.includes("read") || lower.includes("file")) {
    return "读取";
  }
  if (lower.includes("git")) {
    return "Git";
  }
  if (lower.includes("image")) {
    return "图片";
  }
  return normalized;
}

function coerceToolDurationSeconds(toolCall: ToolCall) {
  const value = toolCall as ToolCall & { elapsedSeconds?: unknown };
  const seconds = numberOrNull(value.durationSeconds ?? value.elapsedSeconds);
  if (seconds !== null) {
    return seconds;
  }
  const durationMs = numberOrNull(value.durationMs);
  return durationMs === null ? null : durationMs / 1000;
}

function coerceDurationSeconds(value: ToolCall | ConversationFeedbackEvent) {
  const seconds = numberOrNull(value.durationSeconds);
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
