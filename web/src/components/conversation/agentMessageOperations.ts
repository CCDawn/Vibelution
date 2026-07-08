import type {
  AgentMentalPart,
  AgentMessage,
  AgentMessagePart,
  AgentRuntimeEventPart,
  AgentThoughtPart,
  AgentToolCallPart,
} from "../../agent-thread/types";
import { agentMessageProcessSections } from "./agentMessageSections";

export type AgentMessageOperationKind = "thought" | "mental" | "tool" | "status";

export type AgentMessageOperation = {
  id: string;
  kind: AgentMessageOperationKind;
  label: string;
  rawLabel?: string;
  preserveToolLabel?: boolean;
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

export type AgentMessageOperationLabels = {
  thought: string;
  mental: string;
  status: string;
};

export type AgentMessageOperationGroups = {
  timeline: AgentMessageOperation[];
  thoughts: AgentMessageOperation[];
  mental: AgentMessageOperation[];
  status: AgentMessageOperation[];
  tools: AgentMessageOperation[];
};

export type AgentMessageReActOperationGroup = {
  id: string;
  index: number;
  operations: AgentMessageOperation[];
  thoughtSequence?: number;
  title: string;
  primaryKind: AgentMessageOperationKind;
};

type AgentMessageOperationStatusDisplayInput = {
  name?: string;
  summary?: string;
  resultPreview?: string;
};

const agentOperationGroupsCache = new WeakMap<
  AgentMessage,
  { labels: AgentMessageOperationLabels; groups: AgentMessageOperationGroups }
>();

export function buildAgentMessageOperations(
  message: AgentMessage,
  labels: AgentMessageOperationLabels,
): AgentMessageOperation[] {
  if (message.role !== "assistant") {
    return [];
  }
  const processParts = agentMessageProcessSections(message).flatMap((section) => section.parts);
  const operations = processParts
    .map((part, index) => agentMessagePartToOperation(message, part, index, labels))
    .filter((operation): operation is AgentMessageOperation => operation !== null);
  return normalizeTimelineOperations(operations, message.streaming);
}

export function buildAgentMessageOperationGroups(
  message: AgentMessage,
  labels: AgentMessageOperationLabels,
): AgentMessageOperationGroups {
  const cached = agentOperationGroupsCache.get(message);
  if (cached && cached.labels === labels) {
    return cached.groups;
  }
  const operations = buildAgentMessageOperations(message, labels);
  const groups = {
    timeline: operations,
    thoughts: operations.filter((operation) => operation.kind === "thought"),
    mental: operations.filter((operation) => operation.kind === "mental"),
    status: operations.filter((operation) => operation.kind === "status"),
    tools: operations.filter((operation) => operation.kind === "tool"),
  };
  agentOperationGroupsCache.set(message, { labels, groups });
  return groups;
}

function agentMessagePartToOperation(
  message: AgentMessage,
  part: AgentMessagePart,
  index: number,
  labels: AgentMessageOperationLabels,
): AgentMessageOperation | null {
  if (part.type === "thought") {
    return agentThoughtPartToOperation(message, part, labels);
  }
  if (part.type === "mental") {
    return agentMentalPartToOperation(message, part, labels);
  }
  if (part.type === "tool-call") {
    return agentToolCallPartToOperation(part, index);
  }
  if (part.type === "runtime-event") {
    return agentRuntimeEventPartToOperation(part, index, labels);
  }
  return null;
}

function agentThoughtPartToOperation(
  message: AgentMessage,
  part: AgentThoughtPart,
  labels: AgentMessageOperationLabels,
): AgentMessageOperation | null {
  const text = part.text || part.summary || "";
  if (!text.trim()) {
    return null;
  }
  return {
    id: part.id,
    kind: "thought",
    label: labels.thought,
    status: part.status || (message.streaming ? "running" : "done"),
    summary: compactPreview(part.summary || text),
    durationSeconds: null,
    resultPreview: text,
    sequence: numberOrNull(part.sequence) ?? undefined,
    timestamp: part.timestamp,
  };
}

function agentMentalPartToOperation(
  message: AgentMessage,
  part: AgentMentalPart,
  labels: AgentMessageOperationLabels,
): AgentMessageOperation | null {
  const summary = part.summary.trim();
  if (!summary) {
    return null;
  }
  return {
    id: part.id,
    kind: "mental",
    label: labels.mental,
    status: part.status || (message.streaming ? "running" : "done"),
    summary: compactPreview(summary),
    durationSeconds: null,
    sequence: numberOrNull(part.sequence) ?? undefined,
    timestamp: part.timestamp,
  };
}

function agentToolCallPartToOperation(
  part: AgentToolCallPart,
  index: number,
): AgentMessageOperation {
  const rawLabel = part.name?.trim() || "tool";
  const resultPreview = part.resultPreview || part.summary || "";
  return {
    id: part.id || `agent-tool-${index}`,
    kind: "tool",
    label: rawLabel,
    rawLabel,
    preserveToolLabel: part.source === "legacy-tool-call",
    status: part.status || "done",
    summary: toolSummaryPreview(rawLabel, part.status || "done", part.summary, resultPreview),
    durationSeconds: coerceAgentToolDurationSeconds(part),
    arguments: part.arguments,
    resultPreview: part.resultPreview,
    resultType: part.resultType,
    resultLength: numberOrNull(part.resultLength) ?? undefined,
    error: part.error,
    timeoutSeconds: numberOrNull(part.timeoutSeconds) ?? undefined,
    tracePath: part.tracePath,
    sequence: numberOrNull(part.sequence) ?? undefined,
    timestamp: part.timestamp,
    relatedThoughtSequence: numberOrNull(part.relatedThoughtSequence) ?? undefined,
  };
}

function toolSummaryPreview(
  rawLabel: string,
  status: string,
  summary?: string,
  resultPreview?: string,
) {
  const rawSummary = String(summary ?? "").trim();
  const rawResult = String(resultPreview ?? "").trim();
  const normalizedStatus = normalizeDisplayStatus(status);
  const structuredSummary = extractStructuredToolSummary(rawLabel, rawSummary);
  if (structuredSummary) {
    return compactPreview(structuredSummary, 96);
  }
  if (rawSummary && !looksLikeRawToolPayload(rawSummary)) {
    return compactPreview(rawSummary, 96);
  }
  const structuredResult = extractStructuredToolSummary(rawLabel, rawResult);
  if (structuredResult) {
    return compactPreview(structuredResult, 96);
  }
  if (rawResult && !looksLikeRawToolPayload(rawResult)) {
    return compactPreview(rawResult, 96);
  }
  const candidate = rawSummary || rawResult;
  if (!candidate) {
    return "";
  }
  if (normalizedStatus === "failed") {
    return "执行失败";
  }
  if (isRunningStatus(normalizedStatus)) {
    return "运行中";
  }
  return "执行完成";
}

function extractStructuredToolSummary(rawLabel: string, value: string) {
  const parsed = parseJsonObject(value);
  if (!parsed) {
    return "";
  }
  const lower = String(rawLabel || "").trim().toLowerCase();
  const summary = stringRecordValue(parsed, "dirty_summary")
    || stringRecordValue(parsed, "summary")
    || stringRecordValue(parsed, "message")
    || stringRecordValue(parsed, "error");
  if (summary) {
    return summary;
  }
  if (lower.includes("git")) {
    const changed = numberRecordValue(parsed, "changed_files")
      ?? numberRecordValue(parsed, "changedFileCount")
      ?? numberRecordValue(parsed, "dirty_count");
    if (typeof changed === "number") {
      return `工作区有 ${changed} 个变化文件`;
    }
  }
  return "";
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  const trimmed = String(value || "").trim();
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

function stringRecordValue(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberRecordValue(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function looksLikeRawToolPayload(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return false;
  }
  if ((normalized.startsWith("{") && normalized.endsWith("}")) || (normalized.startsWith("[") && normalized.endsWith("]"))) {
    return true;
  }
  if (/^\|?\s*#\s*\|\s*[^|]+\|\s*[^|]+\|/.test(normalized) && /\|[-:\s|]+\|/.test(normalized)) {
    return true;
  }
  if (/(^|\n)\s*\d+[-:]\s+/.test(normalized)) {
    return true;
  }
  if (/\bSTDERR\b|\bSTDOUT\b|Exit Code|\bTraceback\b|self\._|\bdef\s+\w+\(/.test(normalized)) {
    return true;
  }
  return false;
}

function agentRuntimeEventPartToOperation(
  part: AgentRuntimeEventPart,
  index: number,
  labels: AgentMessageOperationLabels,
): AgentMessageOperation {
  const statusDisplay = statusOperationDisplay({
    name: part.name,
    summary: part.summary,
    resultPreview: part.resultPreview,
  }, labels.status);
  return {
    id: part.id || `agent-runtime-${index}`,
    kind: "status",
    label: statusDisplay.label,
    rawLabel: part.name,
    status: part.status || "running",
    rawStatus: part.status,
    summary: compactPreview(statusDisplay.summary || part.summary || part.resultPreview || ""),
    durationSeconds: null,
    resultPreview: statusDisplay.detail || part.resultPreview,
    error: part.error,
    tracePath: part.tracePath,
    sequence: numberOrNull(part.sequence) ?? undefined,
    timestamp: part.timestamp,
  };
}

export function buildAgentMessageReActOperationGroups(
  operations: AgentMessageOperation[],
): AgentMessageReActOperationGroup[] {
  const groups: AgentMessageReActOperationGroup[] = [];
  let current: AgentMessageReActOperationGroup | null = null;

  const startGroup = (operation: AgentMessageOperation, thoughtSequence?: number) => {
    const group: AgentMessageReActOperationGroup = {
      id: `react-${groups.length + 1}-${operation.id}`,
      index: groups.length + 1,
      operations: [],
      thoughtSequence: operation.kind === "thought" ? operation.sequence : thoughtSequence,
      title: "",
      primaryKind: operation.kind,
    };
    groups.push(group);
    current = group;
    return group;
  };
  const activeGroup = (): AgentMessageReActOperationGroup | null => current;

  for (const operation of operations) {
    let target: AgentMessageReActOperationGroup | null = activeGroup();
    const relatedThoughtSequence =
      typeof operation.relatedThoughtSequence === "number" && operation.relatedThoughtSequence > 0
        ? operation.relatedThoughtSequence
        : undefined;
    if (!target) {
      target = startGroup(operation, relatedThoughtSequence);
    } else if (
      operation.kind === "thought"
      && (reactGroupHasThought(target) || (target.thoughtSequence !== undefined && target.thoughtSequence !== operation.sequence))
    ) {
      target = startGroup(operation);
    } else if (operation.kind !== "thought" && relatedThoughtSequence !== undefined) {
      const targetThoughtSequence = target.thoughtSequence;
      const targetRelatedThoughtSequences = new Set(
        target.operations
          .map((item) => item.relatedThoughtSequence)
          .filter((sequence): sequence is number => typeof sequence === "number" && sequence > 0),
      );
      const targetHasDifferentRelatedThought =
        targetRelatedThoughtSequences.size > 0 && !targetRelatedThoughtSequences.has(relatedThoughtSequence);
      if (
        (targetThoughtSequence !== undefined && targetThoughtSequence !== relatedThoughtSequence)
        || (targetThoughtSequence === undefined && targetHasDifferentRelatedThought)
      ) {
        target = startGroup(operation, relatedThoughtSequence);
      } else if (target.thoughtSequence === undefined) {
        target.thoughtSequence = relatedThoughtSequence;
      }
    }
    if (!target) {
      continue;
    }

    target.operations.push(operation);
    if (operation.kind === "thought" && target.thoughtSequence === undefined) {
      target.thoughtSequence = operation.sequence;
    }
  }

  return groups
    .map((group) => {
      const primaryKind = reActGroupPrimaryKind(group);
      return {
        ...group,
        id: stableReActGroupId(group),
        title: reActGroupTitle(group),
        primaryKind,
      };
    })
    .filter(reActGroupIsDisplayable);
}

function reactGroupHasThought(group: AgentMessageReActOperationGroup) {
  return group.operations.some((operation) => operation.kind === "thought");
}

function stableReActGroupId(group: AgentMessageReActOperationGroup) {
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

function reActGroupIsDisplayable(group: AgentMessageReActOperationGroup) {
  if (group.operations.some((operation) => !["thought", "mental"].includes(operation.kind))) {
    return true;
  }
  return group.operations.some((operation) => operation.status !== "done");
}

function reActGroupPrimaryOperations(group: AgentMessageReActOperationGroup) {
  const actions = group.operations.filter((operation) => !["thought", "mental"].includes(operation.kind));
  const tools = actions.filter((operation) => operation.kind === "tool");
  if (tools.length > 0) {
    return tools;
  }
  if (actions.length > 0) {
    return actions;
  }
  return group.operations;
}

function reActGroupPrimaryKind(group: AgentMessageReActOperationGroup): AgentMessageOperationKind {
  return reActGroupPrimaryOperations(group)[0]?.kind ?? group.operations[0]?.kind ?? "tool";
}

function reActGroupTitle(group: AgentMessageReActOperationGroup) {
  const primaryOperations = reActGroupPrimaryOperations(group);
  const primaryLabels = Array.from(
    new Set(primaryOperations.map((operation) => operation.label).filter(Boolean)),
  ).slice(0, 2);
  return primaryLabels.join("/") || "执行";
}

function normalizeTimelineOperations(
  operations: AgentMessageOperation[],
  messageStreaming: boolean,
): AgentMessageOperation[] {
  const merged: AgentMessageOperation[] = [];
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
  const normalized = merged.map((operation, index) => {
    if (
      isSyntheticFailedOperation(operation)
      && (["thought", "mental"].includes(operation.kind) || index < latestProgressIndex)
    ) {
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
  return compactRepeatedVisibleStatusProgress(compactRepeatedBatchedProgressTools(normalized));
}

function findLatestConcreteProgressIndex(operations: AgentMessageOperation[]) {
  for (let index = operations.length - 1; index >= 0; index -= 1) {
    const operation = operations[index];
    if (operation && ["done", "failed", "degraded", "fallback", "partial", "recovered", "unavailable"].includes(operation.status)) {
      return index;
    }
  }
  return -1;
}

function isSyntheticFailedOperation(operation: AgentMessageOperation) {
  if (operation.status !== "failed") {
    return false;
  }
  if (operation.error?.trim()) {
    return false;
  }
  return operation.kind === "status" || operation.kind === "thought" || operation.kind === "mental";
}

function compactRepeatedBatchedProgressTools(operations: AgentMessageOperation[]) {
  const batchKeysWithFailures = new Set(
    operations
      .filter((operation) => isBatchedProgressTool(operation) && operation.status === "failed")
      .map((operation) => batchedProgressToolKey(operation)),
  );
  const reversedCompacted: AgentMessageOperation[] = [];
  const seenKeys = new Set<string>();
  const droppedThoughtSequences = new Set<number>();

  for (let index = operations.length - 1; index >= 0; index -= 1) {
    const operation = operations[index];
    if (!isBatchedProgressTool(operation) || batchKeysWithFailures.has(batchedProgressToolKey(operation))) {
      reversedCompacted.push(operation);
      continue;
    }
    const key = batchedProgressToolKey(operation);
    if (!seenKeys.has(key)) {
      seenKeys.add(key);
      reversedCompacted.push(operation);
      continue;
    }
    if (typeof operation.relatedThoughtSequence === "number") {
      droppedThoughtSequences.add(operation.relatedThoughtSequence);
    }
  }

  const compacted = reversedCompacted.reverse();
  if (droppedThoughtSequences.size === 0) {
    return compacted;
  }
  const retainedThoughtSequences = new Set(
    compacted
      .map((operation) => operation.relatedThoughtSequence)
      .filter((sequence): sequence is number => typeof sequence === "number"),
  );
  return compacted.filter((operation) => {
    if (
      operation.kind === "thought"
      && typeof operation.sequence === "number"
      && droppedThoughtSequences.has(operation.sequence)
      && !retainedThoughtSequences.has(operation.sequence)
      && operation.status === "done"
    ) {
      return false;
    }
    return true;
  });
}

function compactRepeatedVisibleStatusProgress(operations: AgentMessageOperation[]) {
  const reversedCompacted: AgentMessageOperation[] = [];
  const seenKeys = new Set<string>();
  for (let index = operations.length - 1; index >= 0; index -= 1) {
    const operation = operations[index];
    if (!isVisibleStatusProgress(operation) || operation.error?.trim()) {
      reversedCompacted.push(operation);
      continue;
    }
    const key = visibleStatusProgressKey(operation);
    if (seenKeys.has(key)) {
      continue;
    }
    seenKeys.add(key);
    reversedCompacted.push(operation);
  }
  return reversedCompacted.reverse();
}

function isVisibleStatusProgress(operation: AgentMessageOperation) {
  if (operation.kind !== "status") {
    return false;
  }
  const haystack = [
    operation.rawLabel,
    operation.label,
    operation.summary,
    operation.resultPreview,
  ].map((value) => String(value ?? "").trim().toLowerCase()).filter(Boolean).join(" ");
  return haystack.includes("long_loop_progress")
    || haystack.includes("尚未形成最终回答")
    || haystack.includes("本轮尚未形成最终回答")
    || haystack.includes("工具循环")
    || haystack.includes("tool loop");
}

function visibleStatusProgressKey(operation: AgentMessageOperation) {
  return [
    operation.kind,
    String(operation.rawLabel || operation.label || "").trim().toLowerCase(),
    normalizeDisplayStatus(operation.rawStatus || operation.status),
  ].join(":");
}

function isBatchedProgressTool(operation: AgentMessageOperation) {
  if (operation.kind !== "tool") {
    return false;
  }
  const rawName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  return rawName === "source_collection_stage_writeback_tool"
    || rawName === "source_collection_context_tool";
}

function batchedProgressToolKey(operation: AgentMessageOperation) {
  return String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
}

function mergeThoughtOperation(
  operations: AgentMessageOperation[],
  targetIndex: number,
  next: AgentMessageOperation,
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

function normalizeOperationDisplay(operation: AgentMessageOperation): AgentMessageOperation {
  const rawStatus = operation.rawStatus ?? operation.status;
  return {
    ...operation,
    rawStatus,
    status: normalizeDisplayStatus(operation.status),
    label: operation.kind === "tool" && !operation.preserveToolLabel
      ? displayToolLabel(operation.rawLabel ?? operation.label)
      : operation.label,
  };
}

function normalizeDisplayStatus(status: string) {
  const normalized = String(status || "").trim().toLowerCase();
  if (["done", "success", "completed", "succeeded", "finished", "ready", "observed"].includes(normalized)) {
    return "done";
  }
  if (["degraded", "fallback", "partial", "recovered", "unavailable"].includes(normalized)) {
    return normalized;
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
  event: AgentMessageOperationStatusDisplayInput,
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
    if (key.includes("long_loop_progress") || key.includes("尚未形成最终回答") || key.includes("工具循环")) {
      return zh ? "工具循环" : "Tool loop";
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
  if (label === "工具循环" || label === "Tool loop") {
    return compactPreview(normalized, 96);
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

function displayToolLabel(name: string) {
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
    search_code_tool: "搜索代码",
    get_git_status_summary_tool: "Git 状态",
    image2_generate_tool: "生成图片",
    web_search_tool: "网页搜索",
    web_fetch_tool: "网页读取",
    computer_use_task_tool: "沙盒浏览器",
    task_list_tool: "任务列表",
    task_create_tool: "创建任务",
    task_update_tool: "更新任务",
    source_collection_context_tool: "读取资料上下文",
    source_collection_stage_writeback_tool: "资料提炼回写",
    rg: "搜索",
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

function coerceAgentToolDurationSeconds(toolCall: AgentToolCallPart) {
  const seconds = numberOrNull(toolCall.durationSeconds);
  if (seconds !== null) {
    return seconds;
  }
  const durationMs = numberOrNull(toolCall.durationMs);
  return durationMs === null ? null : durationMs / 1000;
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
