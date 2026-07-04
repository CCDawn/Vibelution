import type {
  AgentMessageOperation,
  AgentMessageReActOperationGroup,
} from "./agentMessageOperations";

export type OperationStateTone = "running" | "failed" | "done" | "pending";

export type OperationStateLabels = {
  running: string;
  failed: string;
  done: string;
  pending: string;
  requesting: string;
  requestFailed: string;
  pendingRequest: string;
  thinking: string;
  generating: string;
  processFailed: string;
  process: string;
  processPending: string;
  thoughtProcess: string;
  toolProcess: string;
  mentalProcess: string;
  status: string;
};

const RUNNING_OPERATION_STATUSES = new Set(["queued", "pending", "running", "thinking", "tooling", "answering"]);

export function operationStatusTone(operation: AgentMessageOperation): OperationStateTone {
  const status = operation.status.trim().toLowerCase();
  if (["failed", "error", "timeout"].includes(status)) {
    return "failed";
  }
  if (isRunningOperationStatus(status)) {
    return "running";
  }
  if (["done", "success", "completed", "succeeded"].includes(status)) {
    return "done";
  }
  return "pending";
}

export function isRunningOperationStatus(status: string) {
  return RUNNING_OPERATION_STATUSES.has(status.trim().toLowerCase());
}

export function operationDisplayLabel(operation: AgentMessageOperation, labels: Pick<OperationStateLabels, "toolProcess">) {
  if (operation.kind !== "tool") {
    return operation.label;
  }
  const normalized = operation.label.trim();
  return normalized || labels.toolProcess;
}

export function operationCollectionTone(operations: AgentMessageOperation[]): OperationStateTone {
  if (operations.some((operation) => isLongLoopProgressOperation(operation) && operationStatusTone(operation) === "running")) {
    return "running";
  }
  if (operations.some((operation) => operationStatusTone(operation) === "failed")) {
    return "failed";
  }
  if (operations.some((operation) => operationStatusTone(operation) === "running")) {
    return "running";
  }
  if (operations.length > 0 && operations.every((operation) => operationStatusTone(operation) === "done")) {
    return "done";
  }
  return "pending";
}

export function reActGroupTone(group: AgentMessageReActOperationGroup): OperationStateTone {
  return operationCollectionTone(group.operations);
}

export function operationStateLabel(tone: string, labels: Pick<OperationStateLabels, "running" | "failed" | "done" | "pending">) {
  if (tone === "running") {
    return labels.running;
  }
  if (tone === "failed") {
    return labels.failed;
  }
  if (tone === "done") {
    return labels.done;
  }
  return labels.pending;
}

export function compactRequestStateLabel(
  tone: string,
  labels: Pick<OperationStateLabels, "requesting" | "requestFailed" | "done" | "pendingRequest">,
) {
  if (tone === "running") {
    return labels.requesting;
  }
  if (tone === "failed") {
    return labels.requestFailed;
  }
  if (tone === "done") {
    return labels.done;
  }
  return labels.pendingRequest;
}

export function isCompactAnswerOnlyRequestProcess(operations: AgentMessageOperation[]) {
  return operations.length > 0 && operations.every((operation) => !shouldShowTimelineOperation(operation));
}

export function hasModelThinkingProcess(operations: AgentMessageOperation[]) {
  return operations.some((operation) => operationMatchesAny(operation, [
    "model_thinking",
    "正在思考",
    "reasoning",
    "model thinking",
  ]));
}

export function compactInternalProcessStateLabel(
  tone: string,
  operations: AgentMessageOperation[],
  labels: Pick<OperationStateLabels, "thinking" | "requesting" | "requestFailed" | "done" | "pendingRequest">,
) {
  if (tone === "running" && hasModelThinkingProcess(operations)) {
    return labels.thinking;
  }
  return compactRequestStateLabel(tone, labels);
}

export function processSummaryTitle(
  tone: string,
  operations: AgentMessageOperation[],
  labels: Pick<
    OperationStateLabels,
    "thinking" | "requesting" | "requestFailed" | "done" | "pendingRequest" | "generating" | "processFailed" | "process" | "processPending"
  >,
) {
  if (isCompactAnswerOnlyRequestProcess(operations)) {
    return compactInternalProcessStateLabel(tone, operations, labels);
  }
  if (tone === "running") {
    return labels.generating;
  }
  if (tone === "failed") {
    return labels.processFailed;
  }
  if (tone === "done") {
    return labels.process;
  }
  return labels.processPending;
}

export function processSummaryMeta(
  operations: AgentMessageOperation[],
  labels: Pick<
    OperationStateLabels,
    "thinking" | "requesting" | "requestFailed" | "done" | "pendingRequest" | "thoughtProcess" | "toolProcess" | "mentalProcess" | "status"
  >,
) {
  if (isCompactAnswerOnlyRequestProcess(operations)) {
    return "";
  }
  const thoughtCount = operations.filter((operation) => operation.kind === "thought").length;
  const toolCount = operations.filter((operation) => operation.kind === "tool").length;
  const mentalCount = operations.filter((operation) => operation.kind === "mental").length;
  const visibleStatusCount = compactVisibleTimelineOperations(
    operations.filter((operation) => operation.kind === "status" && shouldShowTimelineOperation(operation)),
  ).length;
  const parts = [
    thoughtCount > 0 ? `${labels.thoughtProcess} ${thoughtCount}` : "",
    toolCount > 0 ? `${labels.toolProcess} ${toolCount}` : "",
    mentalCount > 0 ? `${labels.mentalProcess} ${mentalCount}` : "",
    visibleStatusCount > 0 ? `${labels.status} ${visibleStatusCount}` : "",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : compactInternalProcessStateLabel(operationCollectionTone(operations), operations, labels);
}

export function processSummaryPreview(
  operations: AgentMessageOperation[],
  labels: Pick<OperationStateLabels, "toolProcess">,
  compactPreview: (value: string, maxLength?: number) => string,
) {
  const tone = operationCollectionTone(operations);
  const running = [...operations]
    .reverse()
    .find((operation) => isRunningOperationStatus(operation.status) && shouldShowTimelineOperation(operation));
  const failed = operations.find((operation) => operationStatusTone(operation) === "failed");
  if (tone !== "running" && tone !== "failed") {
    return "";
  }
  const readable = tone === "failed"
    ? operations.find((operation) => shouldShowTimelineOperation(operation) && operation.summary.trim())
    : undefined;
  const fallback = tone === "failed"
    ? operations.find((operation) => operation.summary.trim() || operation.error?.trim())
    : undefined;
  const preview = tone === "running"
    ? running?.summary.trim()
      || running?.resultPreview?.trim()
      || (running ? operationDisplayLabel(running, labels).trim() : "")
    : failed?.summary.trim()
      || failed?.error?.trim()
      || readable?.summary.trim()
      || fallback?.error?.trim()
      || fallback?.summary.trim()
      || "";
  if (running && isLongLoopProgressOperation(running) && preview.trim()) {
    return compactPreview(`${operationDisplayLabel(running, labels)} · ${preview}`, 120);
  }
  return compactPreview(preview || "", 120);
}

export function operationMatchesAny(operation: AgentMessageOperation, markers: string[]) {
  const haystack = [
    operation.rawLabel,
    operation.label,
    operation.summary,
    operation.resultPreview,
  ].map((item) => String(item ?? "").trim().toLowerCase()).join(" ");
  return markers.some((marker) => haystack.includes(marker));
}

export function isInternalPipelineOperation(operation: AgentMessageOperation) {
  if (operation.kind !== "status") {
    return false;
  }
  return operationMatchesAny(operation, [
    "context_prepare",
    "agent_prepare",
    "model_request",
    "prepare context",
    "bind agent",
    "request model",
    "准备上下文",
    "准备对话上下文",
    "读取当前会话",
    "绑定 agent",
    "唤起对话 agent",
    "请求模型",
    "llm 调用",
    "首个响应片段等待中",
  ]);
}

export function isLongLoopProgressOperation(operation: AgentMessageOperation) {
  if (operation.kind !== "status") {
    return false;
  }
  return operationMatchesAny(operation, [
    "long_loop_progress",
    "工具循环",
    "尚未形成最终回答",
  ]);
}

export function shouldShowTimelineOperation(operation: AgentMessageOperation) {
  if (operation.kind === "status") {
    return isLongLoopProgressOperation(operation) || Boolean(operation.error?.trim());
  }
  return !isInternalPipelineOperation(operation) || Boolean(operation.error?.trim());
}

export function visibleTimelineOperationDedupeKey(operation: AgentMessageOperation) {
  if (operation.kind !== "status" || !isLongLoopProgressOperation(operation) || operation.error?.trim()) {
    return "";
  }
  return [
    operation.kind,
    operation.rawLabel || operation.label,
    operation.rawStatus || operation.status,
  ].join(":");
}

export function compactVisibleTimelineOperations(operations: AgentMessageOperation[]) {
  const compacted: AgentMessageOperation[] = [];
  const indexesByKey = new Map<string, number>();
  for (const operation of operations) {
    const key = visibleTimelineOperationDedupeKey(operation);
    if (!key) {
      compacted.push(operation);
      continue;
    }
    const existingIndex = indexesByKey.get(key);
    if (existingIndex === undefined) {
      indexesByKey.set(key, compacted.length);
      compacted.push(operation);
      continue;
    }
    compacted[existingIndex] = operation;
  }
  return compacted;
}
