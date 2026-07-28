import type { AgentMessageOperation } from "./agentMessageOperations";

export type CodexToolLifecycleStatus = "pending" | "running" | "completed" | "failed" | "degraded";

export type CodexToolRuntimeKind = "terminal" | "tool";

export type CodexTerminalOperationKind = "ExecCommand" | "WriteStdin";

export type CodexToolCall = {
  toolCallId: string;
  rawOperationId: string;
  status: CodexToolLifecycleStatus;
  title: string;
  summary?: string;
  rawToolName?: string;
  runtimeKind: CodexToolRuntimeKind;
  sequence?: number;
  timestamp?: string;
  terminalOperationId?: string;
  tracePath?: string;
  error?: string;
  resultPreview?: string;
  resultType?: string;
  resultLength?: number | null;
  resultKind?: string;
  truncated?: boolean;
  originalLength?: number | null;
};

export type CodexTerminalRequest = {
  displayCommand?: string;
  command?: string[];
  cwd?: string;
};

export type CodexTerminalResult = {
  exitCode?: number | null;
  stdout?: string;
  stderr?: string;
  formattedOutput?: string;
  timedOut?: boolean;
};

export type CodexTerminalOperation = {
  operationId: string;
  toolCallId: string;
  terminalId: string;
  kind: CodexTerminalOperationKind;
  status: CodexToolLifecycleStatus;
  request?: CodexTerminalRequest;
  result?: CodexTerminalResult;
  durationSeconds?: number | null;
  rawOperationId: string;
  tracePath?: string;
};

export type CodexTerminalSession = {
  terminalId: string;
  createdByOperationId: string;
  operationIds: string[];
  status: CodexToolLifecycleStatus;
};

export type CodexTerminalModelObservation = {
  operationId: string;
  toolCallId: string;
  source: "DirectToolCall";
  callItemIds: string[];
  outputItemIds: string[];
};

export type CodexToolLifecycleModel = {
  toolCalls: CodexToolCall[];
  terminalOperations: CodexTerminalOperation[];
  terminalSessions: CodexTerminalSession[];
  modelObservations: CodexTerminalModelObservation[];
};

type RuntimeDiagnosticsOperation = AgentMessageOperation & {
  exitCode?: number | null;
  timedOut?: boolean;
  formattedOutput?: string;
};

export function buildCodexToolLifecycleModel(
  operations: AgentMessageOperation[] | AgentMessageOperation,
): CodexToolLifecycleModel {
  const model: CodexToolLifecycleModel = {
    toolCalls: [],
    terminalOperations: [],
    terminalSessions: [],
    modelObservations: [],
  };
  const normalizedOperations = Array.isArray(operations) ? operations : [operations];

  for (const operation of normalizedOperations) {
    if (operation.kind !== "tool") {
      continue;
    }
    appendToolOperation(model, operation);
  }

  return model;
}

export function normalizeCodexToolLifecycleStatus(status: string | undefined): CodexToolLifecycleStatus {
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

export function codexToolRuntimeKind(operation: AgentMessageOperation): CodexToolRuntimeKind {
  const toolName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  if (terminalSessionKey(operation) || [
    "cli_tool",
    "exec_command",
    "write_stdin",
    "cli_agent_run_tool",
  ].includes(toolName)) {
    return "terminal";
  }
  return "tool";
}

function appendToolOperation(model: CodexToolLifecycleModel, operation: AgentMessageOperation) {
  const runtimeKind = codexToolRuntimeKind(operation);
  const status = normalizeCodexToolLifecycleStatus(operation.status);
  const toolCallId = `tool_call:${operation.id}`;
  let terminalOperationId: string | undefined;

  if (runtimeKind === "terminal") {
    const terminalOperation = terminalOperationFromTool(operation, toolCallId, model.terminalOperations.length, status);
    if (terminalOperation) {
      terminalOperationId = terminalOperation.operationId;
      model.terminalOperations.push(terminalOperation);
      ensureTerminalSession(model, terminalOperation, status);
      model.modelObservations.push({
        operationId: terminalOperation.operationId,
        toolCallId,
        source: "DirectToolCall",
        callItemIds: [toolCallId],
        outputItemIds: status === "pending" || status === "running" ? [] : [`${toolCallId}:output`],
      });
    }
  }

  model.toolCalls.push(compactToolCall({
    toolCallId,
    rawOperationId: operation.id,
    status,
    title: operation.label,
    summary: compactText(operation.summary),
    rawToolName: compactText(operation.rawLabel || operation.label),
    runtimeKind,
    sequence: operation.sequence,
    timestamp: operation.timestamp,
    terminalOperationId,
    tracePath: compactText(operation.tracePath),
    error: compactText(operation.error || (status === "failed" ? operation.summary : "")),
  }));
}

function terminalOperationFromTool(
  operation: AgentMessageOperation,
  toolCallId: string,
  terminalOrdinal: number,
  status: CodexToolLifecycleStatus,
): CodexTerminalOperation | null {
  const diagnostics = operation as RuntimeDiagnosticsOperation;
  const sessionKey = terminalSessionKey(operation);
  if (!sessionKey) {
    return null;
  }
  const operationId = `terminal_operation:${terminalOrdinal}`;
  const terminalId = `terminal:${sessionKey}`;
  const displayCommand = terminalDisplayCommand(operation);
  return compactTerminalOperation({
    operationId,
    toolCallId,
    terminalId,
    kind: terminalOperationKind(operation),
    status,
    request: compactTerminalRequest({
      displayCommand,
      command: displayCommand ? [displayCommand] : undefined,
      cwd: "",
    }),
    result: status === "pending" || status === "running"
      ? undefined
      : compactTerminalResult({
          exitCode: numberOrNull(diagnostics.exitCode),
          stdout: status === "failed" ? "" : compactText(diagnostics.formattedOutput || operation.resultPreview || operation.summary),
          stderr: compactText(operation.error || (status === "failed" ? operation.summary : "")),
          formattedOutput: compactText(operation.error || diagnostics.formattedOutput || operation.resultPreview || operation.summary),
          timedOut: typeof diagnostics.timedOut === "boolean" ? diagnostics.timedOut : undefined,
        }),
    durationSeconds: numberOrNull(operation.durationSeconds),
    rawOperationId: operation.id,
    tracePath: compactText(operation.tracePath),
  });
}

function ensureTerminalSession(
  model: CodexToolLifecycleModel,
  terminalOperation: CodexTerminalOperation,
  status: CodexToolLifecycleStatus,
) {
  const existingSession = model.terminalSessions.find(
    (session) => session.terminalId === terminalOperation.terminalId,
  );
  if (!existingSession) {
    model.terminalSessions.push({
      terminalId: terminalOperation.terminalId,
      createdByOperationId: terminalOperation.operationId,
      operationIds: [terminalOperation.operationId],
      status,
    });
    return;
  }
  if (!existingSession.operationIds.includes(terminalOperation.operationId)) {
    existingSession.operationIds.push(terminalOperation.operationId);
  }
  existingSession.status = mergeTerminalSessionStatus(existingSession.status, status);
}

function mergeTerminalSessionStatus(
  current: CodexToolLifecycleStatus,
  next: CodexToolLifecycleStatus,
): CodexToolLifecycleStatus {
  if (current === "running" || next === "running") {
    return "running";
  }
  if (current === "pending" || next === "pending") {
    return "pending";
  }
  if (current === "failed" || next === "failed") {
    return "failed";
  }
  if (current === "degraded" || next === "degraded") {
    return "degraded";
  }
  return "completed";
}

function terminalSessionKey(operation: AgentMessageOperation) {
  const diagnostics = operation as RuntimeDiagnosticsOperation;
  const explicitSessionId = terminalSessionKeyValue(diagnostics.terminalSessionId);
  if (explicitSessionId) {
    return explicitSessionId;
  }
  const args = operation.arguments ?? {};
  for (const key of ["session_id", "sessionId", "terminal_id", "terminalId"]) {
    const value = args[key];
    const normalized = terminalSessionKeyValue(value);
    if (normalized) {
      return normalized;
    }
  }
  return "";
}

function terminalSessionKeyValue(value: unknown) {
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return "";
}

function terminalOperationKind(operation: AgentMessageOperation): CodexTerminalOperationKind {
  const raw = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  return raw === "write_stdin" ? "WriteStdin" : "ExecCommand";
}

function terminalDisplayCommand(operation: AgentMessageOperation) {
  const rawToolName = String(operation.rawLabel ?? operation.label ?? "").trim().toLowerCase();
  if (rawToolName === "write_stdin") {
    return "";
  }
  const args = operation.arguments ?? {};
  const command = args.cmd ?? args.command;
  if (Array.isArray(command)) {
    return compactText(command.map((item) => String(item ?? "")).join(" "));
  }
  const commandText = typeof command === "string" || typeof command === "number"
    ? String(command)
    : "";
  if (commandText) {
    return compactText(commandText);
  }
  return ["cli_tool", "cli_agent_run_tool"].includes(rawToolName)
    ? compactText(operation.summary)
    : "";
}

function compactToolCall(call: CodexToolCall): CodexToolCall {
  return compactRecord(call) as CodexToolCall;
}

function compactTerminalOperation(operation: CodexTerminalOperation): CodexTerminalOperation {
  return compactRecord(operation) as CodexTerminalOperation;
}

function compactTerminalRequest(request: CodexTerminalRequest): CodexTerminalRequest {
  return compactRecord(request) as CodexTerminalRequest;
}

function compactTerminalResult(result: CodexTerminalResult): CodexTerminalResult {
  return compactRecord(result) as CodexTerminalResult;
}

function compactRecord<T extends Record<string, unknown>>(record: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(record).filter(([, value]) => value !== undefined && value !== ""),
  ) as Partial<T>;
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
