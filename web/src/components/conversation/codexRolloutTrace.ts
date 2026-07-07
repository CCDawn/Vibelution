import type { AgentMessageOperation } from "./agentMessageOperations";
import {
  buildCodexToolLifecycleModel,
  type CodexTerminalModelObservation,
  type CodexTerminalOperation,
  type CodexToolCall,
  type CodexToolLifecycleStatus,
} from "./codexToolLifecycleModel";

export type CodexRolloutTraceEventKind =
  | "ToolCallStarted"
  | "RuntimeStarted"
  | "RuntimeEnded"
  | "ToolCallEnded";

export type CodexRolloutTraceRuntimeKind = "terminal" | "tool" | "status";

export type CodexRolloutTraceStatus = "pending" | "running" | "completed" | "failed" | "degraded";

export type CodexRolloutTraceEvent = {
  id: string;
  kind: CodexRolloutTraceEventKind;
  operationId: string;
  toolCallId?: string;
  terminalOperationId?: string;
  terminalId?: string;
  sequence?: number;
  timestamp?: string;
  status: CodexRolloutTraceStatus;
  title: string;
  summary?: string;
  runtimeKind: CodexRolloutTraceRuntimeKind;
  rawToolName?: string;
  durationSeconds?: number | null;
  exitCode?: number | null;
  timedOut?: boolean;
  tracePath?: string;
  error?: string;
  modelObservationSource?: "DirectToolCall";
};

export function buildCodexRolloutTraceEvents(
  operations: AgentMessageOperation[] | AgentMessageOperation,
): CodexRolloutTraceEvent[] {
  const model = buildCodexToolLifecycleModel(operations);
  return model.toolCalls.flatMap((toolCall) => eventsForToolCall(
    toolCall,
    model.terminalOperations.find((operation) => operation.operationId === toolCall.terminalOperationId),
    model.modelObservations.find((observation) => observation.toolCallId === toolCall.toolCallId),
  ));
}

function eventsForToolCall(
  toolCall: CodexToolCall,
  terminalOperation?: CodexTerminalOperation,
  modelObservation?: CodexTerminalModelObservation,
): CodexRolloutTraceEvent[] {
  const status = rolloutStatus(toolCall.status);
  const startStatus = status === "pending" ? "pending" : "running";
  const startedEvents: CodexRolloutTraceEvent[] = [
    baseEvent(toolCall, "ToolCallStarted", startStatus, terminalOperation, modelObservation),
    baseEvent(toolCall, "RuntimeStarted", startStatus, terminalOperation, modelObservation),
  ];

  if (status === "pending" || status === "running") {
    return startedEvents;
  }

  return [
    ...startedEvents,
    terminalEvent(toolCall, "RuntimeEnded", status, terminalOperation, modelObservation),
    terminalEvent(toolCall, "ToolCallEnded", status, terminalOperation, modelObservation),
  ];
}

function baseEvent(
  toolCall: CodexToolCall,
  kind: CodexRolloutTraceEventKind,
  status: CodexRolloutTraceStatus,
  terminalOperation?: CodexTerminalOperation,
  modelObservation?: CodexTerminalModelObservation,
): CodexRolloutTraceEvent {
  return compactEvent({
    id: eventId(toolCall.rawOperationId, kind),
    kind,
    operationId: toolCall.rawOperationId,
    toolCallId: toolCall.toolCallId,
    terminalOperationId: terminalOperation?.operationId,
    terminalId: terminalOperation?.terminalId,
    sequence: toolCall.sequence,
    timestamp: toolCall.timestamp,
    status,
    title: toolCall.title,
    summary: compactText(toolCall.summary),
    runtimeKind: toolCall.runtimeKind,
    rawToolName: toolCall.rawToolName,
    modelObservationSource: modelObservation?.source,
  });
}

function terminalEvent(
  toolCall: CodexToolCall,
  kind: CodexRolloutTraceEventKind,
  status: CodexRolloutTraceStatus,
  terminalOperation?: CodexTerminalOperation,
  modelObservation?: CodexTerminalModelObservation,
): CodexRolloutTraceEvent {
  return compactEvent({
    ...baseEvent(toolCall, kind, status, terminalOperation, modelObservation),
    durationSeconds: numberOrNull(terminalOperation?.durationSeconds),
    exitCode: numberOrNull(terminalOperation?.result?.exitCode),
    timedOut: typeof terminalOperation?.result?.timedOut === "boolean" ? terminalOperation.result.timedOut : undefined,
    tracePath: compactText(terminalOperation?.tracePath || toolCall.tracePath),
    error: compactText(toolCall.error || terminalOperation?.result?.stderr),
  });
}

function eventId(operationId: string, kind: CodexRolloutTraceEventKind) {
  const suffix: Record<CodexRolloutTraceEventKind, string> = {
    ToolCallStarted: "tool-call-started",
    RuntimeStarted: "runtime-started",
    RuntimeEnded: "runtime-ended",
    ToolCallEnded: "tool-call-ended",
  };
  return `${operationId}-${suffix[kind]}`;
}

function rolloutStatus(status: CodexToolLifecycleStatus): CodexRolloutTraceStatus {
  return status;
}

function compactEvent(event: CodexRolloutTraceEvent): CodexRolloutTraceEvent {
  return Object.fromEntries(
    Object.entries(event).filter(([, value]) => value !== undefined && value !== ""),
  ) as CodexRolloutTraceEvent;
}

function compactText(value: string | undefined) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
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
