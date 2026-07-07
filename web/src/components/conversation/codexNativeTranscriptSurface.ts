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

export type CodexTranscriptSurfaceMode = "native" | "legacy" | "empty";

export type CodexTranscriptSurface = {
  mode: CodexTranscriptSurfaceMode;
  source: "message.codexTranscript" | "legacy_projection" | "none";
  cells: CodexTranscriptCell[];
  hasAssistantMarkdown: boolean;
  suppressLegacyProcess: boolean;
  suppressLegacyResponse: boolean;
  suppressLegacyTurnStatus: boolean;
  fallbackReason?: "native_missing" | "native_empty";
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
  legacyCells: CodexTranscriptCell[] = [],
): CodexTranscriptSurface {
  if (hasUsableNativeCodexTranscript(message)) {
    const cells = codexNativeTranscriptToCells(message.codexTranscript as CodexTranscriptProjection);
    const hasAssistantMarkdown = cells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim()));
    return {
      mode: "native",
      source: "message.codexTranscript",
      cells,
      hasAssistantMarkdown,
      suppressLegacyProcess: true,
      suppressLegacyResponse: hasAssistantMarkdown,
      suppressLegacyTurnStatus: true,
    };
  }
  if (legacyCells.length > 0) {
    return {
      mode: "legacy",
      source: "legacy_projection",
      cells: legacyCells,
      hasAssistantMarkdown: legacyCells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim())),
      suppressLegacyProcess: false,
      suppressLegacyResponse: false,
      suppressLegacyTurnStatus: false,
      fallbackReason: message.codexTranscript ? "native_empty" : "native_missing",
    };
  }
  return {
    mode: "empty",
    source: "none",
    cells: [],
    hasAssistantMarkdown: false,
    suppressLegacyProcess: false,
    suppressLegacyResponse: false,
    suppressLegacyTurnStatus: false,
    fallbackReason: message.codexTranscript ? "native_empty" : "native_missing",
  };
}

export function codexNativeTranscriptToCells(
  transcript: CodexTranscriptProjection,
): CodexTranscriptCell[] {
  const lifecycleModel = normalizeNativeToolLifecycleModel(transcript);
  const rolloutEvents = transcript.rolloutEvents ?? [];
  return (transcript.cells ?? []).map((cell) => {
    const operationIds = [...(cell.operationIds ?? [])];
    const cellRolloutEvents = normalizeNativeRolloutEvents(cell.rolloutTraceEvents?.length
      ? cell.rolloutTraceEvents
      : operationIds.length > 0
        ? rolloutEvents.filter((event) => operationIds.includes(event.operationId))
        : rolloutEvents);
    return {
      id: cell.id,
      kind: cell.kind as CodexTranscriptCellKind,
      messageId: cell.messageId || transcript.messageId,
      status: cell.status as CodexTranscriptCellStatus,
      tone: cell.tone as CodexTranscriptCellTone,
      title: cell.title,
      text: cell.text,
      summary: cell.summary,
      operationIds,
      rolloutTraceEvents: cellRolloutEvents,
      toolLifecycleModel: normalizeNativeToolLifecycleModel(cell.toolLifecycleModel ?? lifecycleModel),
      sourceItemId: cell.sourceItemId,
    };
  });
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
