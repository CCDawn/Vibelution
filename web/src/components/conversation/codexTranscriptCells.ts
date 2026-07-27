import type { AgentMessage, AgentMessagePart, AgentTextPart } from "../../agent-thread/types";
import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageTimelineItem, AgentMessageTimelineItemStatus } from "./agentMessageTimeline";
import { buildCodexRolloutTraceEvents, type CodexRolloutTraceEvent } from "./codexRolloutTrace";
import { buildCodexToolLifecycleModel, type CodexToolLifecycleModel } from "./codexToolLifecycleModel";
import { shouldDisplayTranscriptCell } from "./conversationDisplayProtocol";
import { isInternalStreamingStatusContent } from "./conversationInternalStatus";

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
  channel?: string;
  phase?: string;
  terminal?: boolean;
  provisional?: boolean;
  diagnosticSummary?: Record<string, unknown>;
  title?: string;
  text?: string;
  summary?: string;
  failureCount?: number;
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

  const cells = compactConsecutiveToolFailures(compactTerminalContinuations((options.timelineItems?.length
    ? cellsFromTimelineItems(message.id, options.timelineItems)
    : cellsFromOperations(message.id, options.operations ?? []))
    .filter(shouldDisplayTranscriptCell)));
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
        const failurePresentation = status === "failed"
          ? commandGroupFailurePresentation(item.operations, item.summary)
          : null;
        return {
          id: `${messageId}-${item.id}`,
          kind: status === "failed" ? "error_notice" : "tool_call",
          messageId,
          status,
          tone: cellTone(status),
          title: failurePresentation?.title || item.title,
          summary: failurePresentation?.summary || compactText(item.summary),
          failureCount: failurePresentation?.failureCount,
          diagnosticSummary: failurePresentation?.diagnosticSummary,
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
  const failurePresentation = status === "failed"
    ? toolFailurePresentation(operation, timelineSummary)
    : null;
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
    summary: failurePresentation
      ? failurePresentation.summary
      : compactText(timelineSummary || operation.summary),
    failureCount: failurePresentation ? 1 : undefined,
    diagnosticSummary: failurePresentation?.diagnosticSummary,
    operationIds: [operation.id],
    toolLifecycleModel: operation.kind === "tool" ? buildCodexToolLifecycleModel(operation) : undefined,
    rolloutTraceEvents: buildCodexRolloutTraceEvents(operation),
    sourceItemId,
  };
}

type ToolFailurePresentation = {
  summary: string;
  diagnosticSummary?: Record<string, unknown>;
  identity: string;
  title?: string;
};

function toolFailurePresentation(
  operation: AgentMessageOperation,
  timelineSummary?: string,
): ToolFailurePresentation {
  const candidates = [operation.error, timelineSummary, operation.summary, operation.resultPreview];
  for (const candidate of candidates) {
    const structured = structuredToolFailurePresentation(candidate);
    if (structured) {
      return structured;
    }
    const known = knownToolFailurePresentation(candidate);
    if (known) {
      return known;
    }
  }
  const summary = compactFailureText(operation.error || timelineSummary || operation.summary) || "执行失败";
  return {
    summary,
    identity: normalizeFailureIdentity(summary),
    diagnosticSummary: {
      reasonCode: "tool_failed",
      reasonSummary: summary,
    },
  };
}

function structuredToolFailurePresentation(value: string | undefined): ToolFailurePresentation | null {
  const payload = parseJsonObject(value);
  const status = recordText(payload ?? {}, "status").toLowerCase();
  if (!payload || !["error", "failed", "failure"].includes(status)) {
    return null;
  }
  const code = recordText(payload, "error")
    || recordText(payload, "code")
    || recordText(payload, "failureClass");
  const message = recordText(payload, "message");
  const fallbackMessage = message
    || compactDiagnosticText(recordText(payload, "formattedOutput"))
    || compactDiagnosticText(recordText(payload, "stderr"));
  const identity = normalizeFailureIdentity(code || fallbackMessage || "tool_failed");
  const target = recordTarget(payload);
  const recovery = structuredToolFailureRecovery(code);
  const detail = [
    target ? `目标：${target}` : "",
    recovery ? `建议：${recovery}` : "",
  ].filter(Boolean).join("\n");
  return {
    summary: structuredToolFailureSummary(code, fallbackMessage),
    identity,
    title: failurePresentationTitle(identity),
    diagnosticSummary: {
      reasonCode: code || "tool_failed",
      ...(fallbackMessage ? { reasonSummary: fallbackMessage } : {}),
      ...(detail ? { reasonDetail: detail } : {}),
    },
  };
}

function knownToolFailurePresentation(value: string | undefined): ToolFailurePresentation | null {
  const text = compactText(value);
  if (!text) {
    return null;
  }
  if (/工具调用额度已用尽|tool(?:\s+call)?\s+quota.+(?:exhausted|used up)/i.test(text)) {
    return {
      summary: "本回合工具调用额度已用尽",
      identity: "tool_quota_exhausted",
      title: "工具调用受限",
      diagnosticSummary: {
        reasonCode: "tool_quota_exhausted",
        reasonSummary: compactDiagnosticText(text),
      },
    };
  }
  if (/terminal_stdin_unavailable|终端会话已结束|不能继续写入/i.test(text)) {
    return {
      summary: "终端会话已结束",
      identity: "terminal_stdin_unavailable",
      diagnosticSummary: {
        reasonCode: "terminal_stdin_unavailable",
        reasonSummary: compactDiagnosticText(text),
      },
    };
  }
  return null;
}

function commandGroupFailurePresentation(
  operations: AgentMessageOperation[],
  groupSummary?: string,
): ToolFailurePresentation & { failureCount: number } {
  const failedOperations = operations.filter(
    (operation) => normalizeCellStatus(operation.status) === "failed",
  );
  const candidates = failedOperations.length > 0 ? failedOperations : operations.slice(0, 1);
  const presentations = candidates.map((operation) => toolFailurePresentation(operation, groupSummary));
  const first = presentations[0] ?? {
    summary: "执行失败",
    identity: "tool_failed",
    diagnosticSummary: {
      reasonCode: "tool_failed",
      reasonSummary: "执行失败",
    },
  };
  const sharedIdentity = presentations.every((presentation) => presentation.identity === first.identity);
  if (!sharedIdentity) {
    return {
      summary: `${Math.max(1, candidates.length)} 项工具调用未完成`,
      identity: "multiple_tool_failures",
      title: "部分工具未完成",
      failureCount: Math.max(1, candidates.length),
      diagnosticSummary: {
        reasonCode: "multiple_tool_failures",
        reasonSummary: presentations.map((presentation) => presentation.summary).join("；"),
      },
    };
  }
  return {
    ...first,
    failureCount: Math.max(1, candidates.length),
  };
}

function compactConsecutiveToolFailures(cells: CodexTranscriptCell[]): CodexTranscriptCell[] {
  const compacted: CodexTranscriptCell[] = [];
  for (const cell of cells) {
    const previous = compacted.at(-1);
    const identity = toolFailureIdentity(cell);
    if (!previous || !identity || toolFailureIdentity(previous) !== identity) {
      compacted.push(cell);
      continue;
    }
    const failureCount = (previous.failureCount ?? 1) + (cell.failureCount ?? 1);
    compacted[compacted.length - 1] = {
      ...previous,
      title: groupedFailureTitle(identity, previous.title, cell.title),
      failureCount,
      operationIds: Array.from(new Set([
        ...(previous.operationIds ?? []),
        ...(cell.operationIds ?? []),
      ])),
      rolloutTraceEvents: [
        ...(previous.rolloutTraceEvents ?? []),
        ...(cell.rolloutTraceEvents ?? []),
      ],
    };
  }
  return compacted;
}

function compactTerminalContinuations(cells: CodexTranscriptCell[]): CodexTranscriptCell[] {
  const compacted: CodexTranscriptCell[] = [];
  for (const cell of cells) {
    const originIndex = terminalContinuationOriginIndex(compacted, cell);
    if (originIndex < 0) {
      compacted.push(cell);
      continue;
    }
    compacted[originIndex] = mergeTerminalContinuation(compacted[originIndex], cell);
  }
  return compacted;
}

function terminalContinuationOriginIndex(
  cells: CodexTranscriptCell[],
  continuation: CodexTranscriptCell,
) {
  const sessionIds = terminalSessionIds(continuation);
  if (!isWriteStdinCell(continuation) || !sessionIds.length) {
    return -1;
  }
  if (continuation.status !== "completed" && !isLegacyClosedTerminalContinuation(continuation)) {
    return -1;
  }
  for (let index = cells.length - 1; index >= 0; index -= 1) {
    const candidate = cells[index];
    if (candidate.kind === "assistant_markdown" || candidate.kind === "user") {
      break;
    }
    if (candidate.kind !== "tool_call" || isWriteStdinCell(candidate)) {
      continue;
    }
    if (terminalSessionIds(candidate).some((sessionId) => sessionIds.includes(sessionId))) {
      return index;
    }
  }
  return -1;
}

function mergeTerminalContinuation(
  origin: CodexTranscriptCell,
  continuation: CodexTranscriptCell,
): CodexTranscriptCell {
  const terminalIds = terminalSessionIds(continuation);
  const summary = continuation.status === "completed"
    ? terminalContinuationSummary(continuation) || origin.summary
    : origin.summary;
  const hasNonzeroExit = terminalHasNonzeroExit(origin) || terminalHasNonzeroExit(continuation);
  return {
    ...origin,
    kind: "tool_call",
    status: "completed",
    tone: hasNonzeroExit ? "warning" : "neutral",
    summary,
    failureCount: undefined,
    diagnosticSummary: undefined,
    operationIds: Array.from(new Set([
      ...(origin.operationIds ?? []),
      ...(continuation.operationIds ?? []),
    ])),
    rolloutTraceEvents: [
      ...(origin.rolloutTraceEvents ?? []),
      ...(continuation.rolloutTraceEvents ?? []),
    ],
    toolLifecycleModel: mergeTerminalContinuationModels(
      origin.toolLifecycleModel,
      continuation.toolLifecycleModel,
      terminalIds,
    ),
  };
}

function terminalSessionIds(cell: CodexTranscriptCell) {
  const model = cell.toolLifecycleModel;
  if (!model) {
    return [];
  }
  return Array.from(new Set([
    ...model.terminalSessions.map((session) => session.terminalId),
    ...model.terminalOperations.map((operation) => operation.terminalId),
  ].filter(Boolean)));
}

function isWriteStdinCell(cell: CodexTranscriptCell) {
  const rawName = String(
    cell.toolLifecycleModel?.toolCalls.at(-1)?.rawToolName
    || cell.toolLifecycleModel?.toolCalls.at(-1)?.title
    || cell.title
    || "",
  ).trim().toLowerCase();
  return rawName === "write_stdin";
}

function isLegacyClosedTerminalContinuation(cell: CodexTranscriptCell) {
  if (cell.status !== "failed") {
    return false;
  }
  const reasonCode = String(cell.diagnosticSummary?.reasonCode ?? "").trim().toLowerCase();
  return reasonCode === "terminal_stdin_unavailable"
    || /terminal_stdin_unavailable/i.test(`${cell.summary ?? ""}\n${cell.text ?? ""}`);
}

function terminalContinuationSummary(cell: CodexTranscriptCell) {
  const direct = compactText(cell.summary);
  if (direct) {
    return direct;
  }
  for (const operation of cell.toolLifecycleModel?.terminalOperations ?? []) {
    const result = operation.result;
    const output = compactText(result?.formattedOutput || result?.stdout || result?.stderr);
    if (output) {
      return output;
    }
  }
  return "";
}

function terminalHasNonzeroExit(cell: CodexTranscriptCell) {
  return cell.toolLifecycleModel?.terminalOperations.some((operation) => {
    const exitCode = operation.result?.exitCode;
    return typeof exitCode === "number" && exitCode !== 0;
  }) ?? false;
}

function mergeTerminalContinuationModels(
  origin: CodexToolLifecycleModel | undefined,
  continuation: CodexToolLifecycleModel | undefined,
  terminalIds: string[],
): CodexToolLifecycleModel | undefined {
  if (!origin) {
    return continuation;
  }
  if (!continuation) {
    return origin;
  }
  const terminalIdSet = new Set(terminalIds);
  const originTerminalIdByOperationId = new Map(
    origin.terminalOperations.map((operation) => [operation.operationId, operation.terminalId]),
  );
  const continuationOperationIds = new Map(
    continuation.terminalOperations.map((operation, index) => [
      operation.operationId,
      `terminal_operation:${origin.terminalOperations.length + index}`,
    ]),
  );
  const completionByTerminalId = new Map(
    continuation.terminalOperations
      .filter((operation) => terminalIdSet.has(operation.terminalId))
      .map((operation) => [operation.terminalId, operation]),
  );
  const terminalOperations = [
    ...origin.terminalOperations.map((operation) => {
      const completion = completionByTerminalId.get(operation.terminalId);
      return terminalIdSet.has(operation.terminalId)
        ? { ...operation, status: "completed" as const, result: completion?.result ?? operation.result }
        : operation;
    }),
    ...continuation.terminalOperations.map((operation) => ({
      ...operation,
      operationId: continuationOperationIds.get(operation.operationId) ?? operation.operationId,
    })),
  ];
  const toolCalls = [
    ...origin.toolCalls.map((toolCall) => {
      const terminalId = toolCall.terminalOperationId
        ? originTerminalIdByOperationId.get(toolCall.terminalOperationId)
        : "";
      return terminalId && terminalIdSet.has(terminalId)
        ? { ...toolCall, status: "completed" as const }
        : toolCall;
    }),
    ...continuation.toolCalls.map((toolCall) => ({
      ...toolCall,
      terminalOperationId: toolCall.terminalOperationId
        ? continuationOperationIds.get(toolCall.terminalOperationId) ?? toolCall.terminalOperationId
        : undefined,
    })),
  ];
  const terminalSessions = origin.terminalSessions.map((session) => ({
    ...session,
    operationIds: [...session.operationIds],
    status: terminalIdSet.has(session.terminalId) ? "completed" as const : session.status,
  }));
  const sessionIndexByTerminalId = new Map(
    terminalSessions.map((session, index) => [session.terminalId, index]),
  );
  for (const session of continuation.terminalSessions) {
    const operationIds = session.operationIds.map(
      (operationId) => continuationOperationIds.get(operationId) ?? operationId,
    );
    const existingIndex = sessionIndexByTerminalId.get(session.terminalId);
    if (existingIndex === undefined) {
      terminalSessions.push({
        ...session,
        operationIds,
        status: terminalIdSet.has(session.terminalId) ? "completed" : session.status,
      });
      sessionIndexByTerminalId.set(session.terminalId, terminalSessions.length - 1);
      continue;
    }
    const existing = terminalSessions[existingIndex];
    terminalSessions[existingIndex] = {
      ...existing,
      operationIds: Array.from(new Set([...existing.operationIds, ...operationIds])),
      status: terminalIdSet.has(session.terminalId) ? "completed" : session.status,
    };
  }
  return {
    toolCalls,
    terminalOperations,
    terminalSessions,
    modelObservations: [
      ...origin.modelObservations,
      ...continuation.modelObservations.map((observation) => ({
        ...observation,
        operationId: continuationOperationIds.get(observation.operationId) ?? observation.operationId,
      })),
    ],
  };
}

export function normalizeCodexTranscriptToolFailures(
  cells: CodexTranscriptCell[],
): CodexTranscriptCell[] {
  return compactConsecutiveToolFailures(cells.map((cell) => {
    if (cell.kind !== "error_notice" || cell.status !== "failed" || !cell.operationIds?.length) {
      return cell;
    }
    const sourceText = cell.text?.trim() || cell.summary?.trim() || "";
    const presentation = toolFailurePresentation({
      id: cell.id,
      kind: "tool",
      label: cell.title || "工具调用",
      status: "failed",
      summary: sourceText,
      error: sourceText,
      durationSeconds: null,
    });
    const existingReasonCode = String(cell.diagnosticSummary?.reasonCode ?? "").trim();
    const identity = existingReasonCode
      ? normalizeFailureIdentity(existingReasonCode)
      : presentation.identity;
    return {
      ...cell,
      title: failurePresentationTitle(identity) || presentation.title || cell.title,
      text: undefined,
      summary: presentation.summary,
      failureCount: cell.failureCount ?? 1,
      diagnosticSummary: {
        ...(presentation.diagnosticSummary ?? {}),
        ...(cell.diagnosticSummary ?? {}),
        reasonCode: existingReasonCode
          || String(presentation.diagnosticSummary?.reasonCode ?? "").trim()
          || "tool_failed",
      },
    };
  }));
}

function toolFailureIdentity(cell: CodexTranscriptCell) {
  if (cell.kind !== "error_notice" || !cell.operationIds?.length) {
    return "";
  }
  const reasonCode = String(cell.diagnosticSummary?.reasonCode ?? "").trim();
  if (!reasonCode || reasonCode === "tool_failed") {
    return "";
  }
  return normalizeFailureIdentity(reasonCode);
}

function groupedFailureTitle(identity: string, previousTitle?: string, nextTitle?: string) {
  const semanticTitle = failurePresentationTitle(identity);
  if (semanticTitle) {
    return semanticTitle;
  }
  if (previousTitle?.trim() && previousTitle.trim() === nextTitle?.trim()) {
    return previousTitle.trim();
  }
  return "工具调用失败";
}

function failurePresentationTitle(identity: string) {
  if (identity === "tool_quota_exhausted") {
    return "工具调用受限";
  }
  if (identity === "terminal_stdin_unavailable") {
    return "";
  }
  return "";
}

function normalizeFailureIdentity(value: string) {
  return compactText(value).toLowerCase().replace(/\s+/g, "_");
}

function parseJsonObject(value: string | undefined): Record<string, unknown> | null {
  const trimmed = String(value ?? "").trim();
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

function recordText(record: Record<string, unknown>, key: string) {
  const value = record[key];
  return typeof value === "string" ? value.trim() : "";
}

function recordTarget(record: Record<string, unknown>) {
  const target = record.target;
  if (typeof target === "string") {
    return target.trim();
  }
  if (!target || typeof target !== "object" || Array.isArray(target)) {
    return "";
  }
  const targetRecord = target as Record<string, unknown>;
  return recordText(targetRecord, "filePath") || recordText(targetRecord, "symbol");
}

function structuredToolFailureSummary(code: string, message: string) {
  const summaries: Record<string, string> = {
    target_not_indexed: "索引未就绪",
    directory_not_indexed: "目录未建立索引",
    target_not_found: "目标不存在",
    target_outside_project: "目标超出项目范围",
    terminal_stdin_unavailable: "终端会话已结束",
    tool_quota_exhausted: "本回合工具调用额度已用尽",
  };
  return summaries[normalizeFailureIdentity(code)] || compactFailureText(message || code || "执行失败");
}

function structuredToolFailureRecovery(code: string) {
  if (code === "target_not_indexed") {
    return "刷新索引后重试";
  }
  if (code === "directory_not_indexed") {
    return "确认目录属于索引范围后重试";
  }
  return "";
}

function compactFailureText(value: string | undefined) {
  const normalized = compactText(value);
  const maxLength = 96;
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength - 1).trimEnd()}…`
    : normalized;
}

function compactDiagnosticText(value: string | undefined) {
  const normalized = compactText(value);
  const maxLength = 240;
  return normalized.length > maxLength
    ? `${normalized.slice(0, maxLength - 1).trimEnd()}…`
    : normalized;
}

function answerTextFromMessage(message: AgentMessage) {
  const text = message.parts
    .filter(isAssistantAnswerTextPart)
    .map((part) => part.text.trim())
    .filter(Boolean)
    .join("\n\n");
  return isInternalStreamingStatusContent(text) ? "" : text;
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
