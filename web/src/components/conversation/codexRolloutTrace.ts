import type { AgentMessageOperation } from "./agentMessageOperations";

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
};

type RuntimeDiagnosticsOperation = AgentMessageOperation & {
  exitCode?: number | null;
  timedOut?: boolean;
};

export function buildCodexRolloutTraceEvents(
  operations: AgentMessageOperation[] | AgentMessageOperation,
): CodexRolloutTraceEvent[] {
  const normalizedOperations = Array.isArray(operations) ? operations : [operations];
  return normalizedOperations.flatMap((operation) => eventsForOperation(operation));
}

function eventsForOperation(operation: AgentMessageOperation): CodexRolloutTraceEvent[] {
  if (operation.kind !== "tool") {
    return [];
  }

  const status = normalizeRolloutTraceStatus(operation.status);
  const runtimeKind = rolloutRuntimeKind(operation);
  const startStatus = status === "pending" ? "pending" : "running";
  const startedEvents: CodexRolloutTraceEvent[] = [
    baseEvent(operation, "ToolCallStarted", startStatus, runtimeKind),
    baseEvent(operation, "RuntimeStarted", startStatus, runtimeKind),
  ];

  if (status === "pending" || status === "running") {
    return startedEvents;
  }

  return [
    ...startedEvents,
    terminalEvent(operation, "RuntimeEnded", status, runtimeKind),
    terminalEvent(operation, "ToolCallEnded", status, runtimeKind),
  ];
}

function baseEvent(
  operation: AgentMessageOperation,
  kind: CodexRolloutTraceEventKind,
  status: CodexRolloutTraceStatus,
  runtimeKind: CodexRolloutTraceRuntimeKind,
): CodexRolloutTraceEvent {
  return compactEvent({
    id: eventId(operation.id, kind),
    kind,
    operationId: operation.id,
    sequence: operation.sequence,
    timestamp: operation.timestamp,
    status,
    title: operation.label,
    summary: compactText(operation.summary),
    runtimeKind,
    rawToolName: rawToolName(operation),
  });
}

function terminalEvent(
  operation: AgentMessageOperation,
  kind: CodexRolloutTraceEventKind,
  status: CodexRolloutTraceStatus,
  runtimeKind: CodexRolloutTraceRuntimeKind,
): CodexRolloutTraceEvent {
  const diagnostics = operation as RuntimeDiagnosticsOperation;
  return compactEvent({
    ...baseEvent(operation, kind, status, runtimeKind),
    durationSeconds: numberOrNull(operation.durationSeconds),
    exitCode: numberOrNull(diagnostics.exitCode),
    timedOut: typeof diagnostics.timedOut === "boolean" ? diagnostics.timedOut : undefined,
    tracePath: compactText(operation.tracePath),
    error: compactText(operation.error || (status === "failed" ? operation.summary : "")),
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

function rolloutRuntimeKind(operation: AgentMessageOperation): CodexRolloutTraceRuntimeKind {
  const haystack = [
    operation.rawLabel,
    operation.label,
    operation.summary,
  ].map((item) => String(item ?? "").toLowerCase()).join(" ");
  if ([
    "cli_tool",
    "exec",
    "shell",
    "command",
    "powershell",
    "cmd.exe",
    "bash",
    "npm ",
    "pytest",
    "vitest",
    "rg ",
    "命令",
  ].some((marker) => haystack.includes(marker))) {
    return "terminal";
  }
  return "tool";
}

function normalizeRolloutTraceStatus(status: string | undefined): CodexRolloutTraceStatus {
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

function rawToolName(operation: AgentMessageOperation) {
  return compactText(operation.rawLabel || operation.label);
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
