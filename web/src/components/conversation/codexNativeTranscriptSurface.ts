import type { CodexTranscriptProjection, ConversationMessage } from "../../api/types";
import type {
  CodexRolloutTraceEvent,
  CodexRolloutTraceEventKind,
  CodexRolloutTraceRuntimeKind,
  CodexRolloutTraceStatus,
} from "./codexRolloutTrace";
import {
  normalizeCodexToolLifecycleStatus,
  type CodexTerminalModelObservation,
  type CodexTerminalOperation,
  type CodexTerminalSession,
  type CodexToolCall,
  type CodexToolLifecycleModel,
  type CodexToolLifecycleStatus,
} from "./codexToolLifecycleModel";
import type {
  CodexTranscriptCell,
  CodexTranscriptCellKind,
  CodexTranscriptCellStatus,
  CodexTranscriptCellTone,
} from "./codexTranscriptCells";
import { normalizeCodexTranscriptToolFailures } from "./codexTranscriptCells";
import { shouldDisplayTranscriptCell } from "./conversationDisplayProtocol";
import { isNoFinalAnswerStatusContent } from "./conversationInternalStatus";
import { conversationToolSemanticLabel } from "./conversationToolSemanticLabel";

export type CodexTranscriptSurfaceMode = "native" | "empty";

export type CodexTranscriptProjectionGapReason =
  | "native_missing"
  | "native_empty"
  | "native_unusable";

export type CodexTranscriptProjectionGap = {
  reason: CodexTranscriptProjectionGapReason;
  projectedCellCount: number;
};

export type CodexTranscriptSurface = {
  mode: CodexTranscriptSurfaceMode;
  source: "message.codexTranscript" | "none";
  cells: CodexTranscriptCell[];
  hasAssistantMarkdown: boolean;
  suppressProjectedProcess: boolean;
  suppressProjectedResponse: boolean;
  suppressProjectedTurnStatus: boolean;
  suppressProjectedError: boolean;
  projectionGap?: CodexTranscriptProjectionGap;
};

type NativeToolLifecycleModelInput = Partial<
  Pick<CodexTranscriptProjection, "toolCalls" | "terminalOperations" | "terminalSessions" | "modelObservations">
>;

export function hasUsableNativeCodexTranscript(message: ConversationMessage) {
  const transcript = message.codexTranscript;
  return Boolean(
    message.role === "assistant"
    && transcript
    && String(transcript.source ?? "").trim() === "native"
    && Array.isArray(transcript.cells)
    && transcript.cells.length > 0,
  );
}

export function resolveCodexTranscriptSurface(
  message: ConversationMessage,
  projectedCells: CodexTranscriptCell[] = [],
): CodexTranscriptSurface {
  if (hasUsableNativeCodexTranscript(message)) {
    const transcript = message.codexTranscript as CodexTranscriptProjection;
    const cells = codexNativeTranscriptToCells(transcript);
    const hasAssistantMarkdown = cells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim()));
    const hasNoFinalAnswerStatus = isNoFinalAnswerStatusContent(String(message.content ?? ""));
    const hasNativeProcessProjection = hasNativeProcessCells(cells) || hasNativeLifecycleProjection(transcript);
    const suppressProjectedError = cells.some((cell) => (
      cell.kind === "error_notice"
      || (cell.terminal === true && cell.status === "failed")
    ));
    return {
      mode: "native",
      source: "message.codexTranscript",
      cells,
      hasAssistantMarkdown,
      suppressProjectedProcess: hasNativeProcessProjection,
      suppressProjectedResponse: hasAssistantMarkdown || suppressProjectedError,
      suppressProjectedTurnStatus: suppressProjectedError
        || (hasNoFinalAnswerStatus ? false : hasAssistantMarkdown || hasNativeProcessProjection),
      suppressProjectedError,
    };
  }
  return {
    mode: "empty",
    source: "none",
    cells: [],
    hasAssistantMarkdown: false,
    suppressProjectedProcess: false,
    suppressProjectedResponse: false,
    suppressProjectedTurnStatus: false,
    suppressProjectedError: false,
    projectionGap: {
      reason: nativeTranscriptProjectionGapReason(message),
      projectedCellCount: projectedCells.length,
    },
  };
}

export function codexNativeTranscriptToCells(
  transcript: CodexTranscriptProjection,
): CodexTranscriptCell[] {
  const lifecycleModel = normalizeNativeToolLifecycleModel(transcript);
  const rolloutEvents = transcript.rolloutEvents ?? [];
  return normalizeCodexTranscriptToolFailures((transcript.cells ?? [])
    .map((cell) => {
      const legacyMarkdown = "markdown" in cell && typeof cell.markdown === "string" ? cell.markdown : "";
      const operationIds = [...(cell.operationIds ?? [])];
      const cellRolloutEvents = normalizeNativeRolloutEvents(cell.rolloutTraceEvents?.length
        ? cell.rolloutTraceEvents
        : operationIds.length > 0
          ? rolloutEvents.filter((event) => operationIds.includes(event.operationId))
          : rolloutEvents);
      const cellLifecycleModel = normalizeNativeToolLifecycleModel(cell.toolLifecycleModel ?? lifecycleModel);
      const commandSource = nativeCellCommandSource(operationIds, cellLifecycleModel);
      const isToolCell = cell.kind === "tool_call" || nativeCellHasToolCall(operationIds, cellLifecycleModel);
      const rawTitle = String(cell.title ?? "").trim();
      const title = isToolCell
        ? conversationToolSemanticLabel({
            toolName: rawTitle,
            summary: cell.summary,
            commandSource,
          })
        : cell.title;
      return {
        id: cell.id,
        kind: cell.kind as CodexTranscriptCellKind,
        messageId: cell.messageId || transcript.messageId,
        status: cell.status as CodexTranscriptCellStatus,
        tone: cell.tone as CodexTranscriptCellTone,
        title,
        text: cell.text || legacyMarkdown,
        summary: cell.summary,
        failureCount: nativeCellFailureCount(cell),
        channel: cell.channel,
        phase: cell.phase,
        terminal: cell.terminal,
        provisional: cell.provisional,
        diagnosticSummary: isToolCell && rawTitle && title !== rawTitle
          ? { ...(cell.diagnosticSummary ?? {}), rawToolName: rawTitle }
          : cell.diagnosticSummary,
        operationIds,
        rolloutTraceEvents: cellRolloutEvents,
        toolLifecycleModel: cellLifecycleModel,
        sourceItemId: cell.sourceItemId,
      };
    })
    .filter(shouldDisplayTranscriptCell));
}

function nativeCellFailureCount(cell: CodexTranscriptProjection["cells"][number]) {
  const failureCount = Number((cell as typeof cell & { failureCount?: number }).failureCount);
  return Number.isFinite(failureCount) && failureCount > 0 ? failureCount : undefined;
}

function nativeCellHasToolCall(operationIds: string[], model: CodexToolLifecycleModel) {
  return model.toolCalls.some((toolCall) => (
    operationIds.includes(toolCall.rawOperationId)
    || operationIds.includes(toolCall.toolCallId)
  ));
}

function nativeCellCommandSource(operationIds: string[], model: CodexToolLifecycleModel) {
  const toolCallIds = new Set(
    model.toolCalls
      .filter((toolCall) => (
        operationIds.includes(toolCall.rawOperationId)
        || operationIds.includes(toolCall.toolCallId)
      ))
      .map((toolCall) => toolCall.toolCallId),
  );
  return model.terminalOperations
    .filter((operation) => (
      operationIds.includes(operation.rawOperationId)
      || operationIds.includes(operation.operationId)
      || toolCallIds.has(operation.toolCallId)
    ))
    .map((operation) => operation.request);
}

function hasNativeProcessCells(cells: CodexTranscriptCell[]) {
  return cells.some((cell) => cell.kind !== "assistant_markdown" && cell.kind !== "user");
}

function hasNativeLifecycleProjection(transcript: CodexTranscriptProjection) {
  return Boolean(
    (transcript.toolCalls?.length ?? 0) > 0
    || (transcript.terminalOperations?.length ?? 0) > 0
    || (transcript.terminalSessions?.length ?? 0) > 0
    || (transcript.modelObservations?.length ?? 0) > 0
    || (transcript.rolloutEvents?.length ?? 0) > 0,
  );
}

function normalizeNativeRolloutEvents(events: NonNullable<CodexTranscriptProjection["rolloutEvents"]>): CodexRolloutTraceEvent[] {
  return events
    .map((event): CodexRolloutTraceEvent | null => {
      const kind = normalizeRolloutEventKind(event.kind);
      if (!kind) {
        return null;
      }
      return {
        ...event,
        kind,
        status: normalizeRolloutStatus(event.status),
        runtimeKind: normalizeRolloutRuntimeKind(event.runtimeKind),
        modelObservationSource: event.modelObservationSource === "DirectToolCall" ? "DirectToolCall" : undefined,
      };
    })
    .filter((event): event is CodexRolloutTraceEvent => event !== null);
}

function normalizeRolloutEventKind(kind: string | undefined): CodexRolloutTraceEventKind | null {
  if (
    kind === "ToolCallStarted"
    || kind === "RuntimeStarted"
    || kind === "RuntimeEnded"
    || kind === "ToolCallEnded"
  ) {
    return kind;
  }
  return null;
}

function normalizeRolloutStatus(status: string | undefined): CodexRolloutTraceStatus {
  return normalizeLifecycleStatus(status);
}

function normalizeRolloutRuntimeKind(runtimeKind: string | undefined): CodexRolloutTraceRuntimeKind {
  if (runtimeKind === "terminal" || runtimeKind === "status") {
    return runtimeKind;
  }
  return "tool";
}

function normalizeNativeToolLifecycleModel(model: NativeToolLifecycleModelInput): CodexToolLifecycleModel {
  return {
    toolCalls: (model.toolCalls ?? []).map(normalizeNativeToolCall),
    terminalOperations: (model.terminalOperations ?? []).map(normalizeNativeTerminalOperation),
    terminalSessions: (model.terminalSessions ?? []).map(normalizeNativeTerminalSession),
    modelObservations: (model.modelObservations ?? []).map(normalizeNativeModelObservation).filter(
      (observation): observation is CodexTerminalModelObservation => observation !== null,
    ),
  };
}

function normalizeNativeToolCall(toolCall: NonNullable<CodexTranscriptProjection["toolCalls"]>[number]): CodexToolCall {
  return {
    ...toolCall,
    status: normalizeLifecycleStatus(toolCall.status),
    runtimeKind: toolCall.runtimeKind === "terminal" ? "terminal" : "tool",
  };
}

function normalizeNativeTerminalOperation(
  operation: NonNullable<CodexTranscriptProjection["terminalOperations"]>[number],
): CodexTerminalOperation {
  return {
    ...operation,
    kind: operation.kind === "WriteStdin" ? "WriteStdin" : "ExecCommand",
    status: normalizeLifecycleStatus(operation.status),
  };
}

function normalizeNativeTerminalSession(
  session: NonNullable<CodexTranscriptProjection["terminalSessions"]>[number],
): CodexTerminalSession {
  return {
    ...session,
    status: normalizeLifecycleStatus(session.status),
  };
}

function normalizeNativeModelObservation(
  observation: NonNullable<CodexTranscriptProjection["modelObservations"]>[number],
): CodexTerminalModelObservation | null {
  if (observation.source !== "DirectToolCall") {
    return null;
  }
  return {
    ...observation,
    source: "DirectToolCall",
  };
}

function normalizeLifecycleStatus(status: string | undefined): CodexToolLifecycleStatus {
  return normalizeCodexToolLifecycleStatus(status);
}

function nativeTranscriptProjectionGapReason(message: ConversationMessage): CodexTranscriptProjectionGapReason {
  if (!message.codexTranscript) {
    return "native_missing";
  }
  if (message.role !== "assistant" || String(message.codexTranscript.source ?? "").trim() !== "native") {
    return "native_unusable";
  }
  if (!Array.isArray(message.codexTranscript.cells) || message.codexTranscript.cells.length === 0) {
    return "native_empty";
  }
  return "native_unusable";
}
