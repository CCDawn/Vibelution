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
import {
  normalizeCodexTranscriptToolFailures,
  settleCodexTranscriptActiveStatuses,
} from "./codexTranscriptCells";
import {
  codexTranscriptFromTurnItems,
  finalAnswerTextFromTurnItems,
} from "../../routes/chatTurnProtocol";
import { shouldDisplayTranscriptCell } from "./conversationDisplayProtocol";
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
  source: "turnItems" | "none";
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
  return message.role === "assistant" && message.turnItems.length > 0;
}

/** True when native assistant_markdown already owns a displayable final answer. */
export function nativeAssistantMarkdownCoversProjectedAnswer(
  cells: CodexTranscriptCell[],
  projectedAnswer: string,
) {
  const answerCells = cells.filter((cell) => (
    cell.kind === "assistant_markdown"
    && Boolean(cell.text?.trim())
    && String(cell.phase ?? "").trim().toLowerCase() !== "commentary"
  ));
  const nativeAnswer = answerCells
    .map((cell) => String(cell.text ?? "").trim())
    .filter(Boolean)
    .join("\n\n");
  return Boolean(nativeAnswer) && (
    !projectedAnswer
    || nativeAnswer === projectedAnswer
    || nativeAnswer.includes(projectedAnswer)
    || projectedAnswer.includes(nativeAnswer)
  );
}

const codexTranscriptSurfaceCache = new WeakMap<
  ConversationMessage,
  { projectedCells: CodexTranscriptCell[]; surface: CodexTranscriptSurface }
>();

export function resolveCodexTranscriptSurface(
  message: ConversationMessage,
  projectedCells: CodexTranscriptCell[] = [],
): CodexTranscriptSurface {
  if (message.role === "assistant" && hasUsableNativeCodexTranscript(message)) {
    const cached = codexTranscriptSurfaceCache.get(message);
    if (cached && cached.projectedCells === projectedCells) {
      return cached.surface;
    }
    const transcript = codexTranscriptFromTurnItems(message.turnItems);
    const cells = codexNativeTranscriptToCells(transcript, {
      turnStreaming: message.status === "running",
    });
    const hasAssistantMarkdown = cells.some((cell) => cell.kind === "assistant_markdown" && Boolean(cell.text?.trim()));
    const projectedAnswer = finalAnswerTextFromTurnItems(message.turnItems);
    const nativeCoversProjectedAnswer = nativeAssistantMarkdownCoversProjectedAnswer(cells, projectedAnswer);
    // Only suppress the outer process rail when process is actually rendered as cells.
    // Lifecycle metadata alone must not hide feedback/timeline tools (would drop the process UI).
    const hasNativeProcessProjection = hasNativeProcessCells(cells);
    const hasLifecycleHints = hasNativeLifecycleProjection(transcript);
    const suppressProjectedError = cells.some((cell) => (
      cell.kind === "error_notice"
      || (cell.terminal === true && cell.status === "failed")
    ));
    // Only hide the projected response when native cells already own the final answer.
    // Short orphan fragments (e.g. "存。") must not suppress a long committed content body.
    const suppressProjectedResponse = suppressProjectedError
      || (hasAssistantMarkdown && nativeCoversProjectedAnswer);
    const surface: CodexTranscriptSurface = {
      mode: "native",
      source: "turnItems",
      cells,
      hasAssistantMarkdown,
      // Codex order: process cells then final inside the surface. Outer processNode is
      // only for fallback timelines when cells do not already carry process rows.
      suppressProjectedProcess: hasNativeProcessProjection,
      suppressProjectedResponse,
      suppressProjectedTurnStatus: suppressProjectedError
        || suppressProjectedResponse || hasNativeProcessProjection || hasLifecycleHints,
      suppressProjectedError,
    };
    codexTranscriptSurfaceCache.set(message, { projectedCells, surface });
    return surface;
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
  options?: { turnStreaming?: boolean },
): CodexTranscriptCell[] {
  const lifecycleModel = normalizeNativeToolLifecycleModel(transcript);
  const rolloutEvents = transcript.rolloutEvents ?? [];
  return settleCodexTranscriptActiveStatuses(
    normalizeCodexTranscriptToolFailures((transcript.cells ?? [])
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
      .filter(shouldDisplayTranscriptCell)),
    { turnStreaming: options?.turnStreaming },
  );
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

/**
 * Whether native transcript cells already own the process rail
 * (tools, reasoning, commentary, errors, status, stream tail…).
 * Exported for display-plan dual-paint guards and tests.
 */
export function hasNativeProcessCells(cells: readonly CodexTranscriptCell[]) {
  // Process trail includes tools/reasoning/status AND commentary intermediate text.
  // Treating all assistant_markdown as "not process" left commentary-only turns with
  // suppressProjectedProcess=false, so feedback "thought" + native commentary both painted.
  return cells.some((cell) => {
    if (cell.kind === "user") {
      return false;
    }
    if (cell.kind === "assistant_markdown") {
      const phase = String(cell.phase || "").trim().toLowerCase();
      const channel = String(cell.channel || "").trim().toLowerCase();
      return phase === "commentary" || phase === "interim" || channel === "commentary";
    }
    // tool_call, reasoning_summary, error_notice, status, stream_tail, …
    return true;
  });
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
  if (message.role !== "assistant" || message.turnItems.length === 0) {
    return "native_missing";
  }
  return "native_empty";
}
