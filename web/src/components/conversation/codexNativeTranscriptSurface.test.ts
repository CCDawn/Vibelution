import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  hasUsableNativeCodexTranscript,
  resolveCodexTranscriptSurface,
} from "./codexNativeTranscriptSurface";

const fallbackCells: CodexTranscriptCell[] = [
  {
    id: "legacy-tool",
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "legacy",
  },
];

function message(patch: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "legacy answer",
    timestamp: "2026-07-07T10:45:00Z",
    ...patch,
  };
}

describe("codexNativeTranscriptSurface", () => {
  it("prefers backend native transcript cells over legacy fallback cells", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "native-answer",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            text: "native answer",
          },
        ],
        toolCalls: [
          {
            toolCallId: "tool_call:native",
            rawOperationId: "native",
            status: "completed",
            title: "native tool",
            runtimeKind: "tool",
          },
        ],
        rolloutEvents: [
          {
            id: "native-tool-call-started",
            kind: "ToolCallStarted",
            operationId: "native",
            status: "running",
            title: "native tool",
            runtimeKind: "tool",
          },
        ],
      },
    }), fallbackCells);

    expect(surface.mode).toBe("native");
    expect(surface.source).toBe("message.codexTranscript");
    expect(surface.cells).toHaveLength(1);
    expect(surface.cells[0]).toMatchObject({
      id: "native-answer",
      kind: "assistant_markdown",
      text: "native answer",
      toolLifecycleModel: expect.objectContaining({
        toolCalls: [expect.objectContaining({ toolCallId: "tool_call:native" })],
      }),
      rolloutTraceEvents: [expect.objectContaining({ kind: "ToolCallStarted" })],
    });
    expect(surface.hasAssistantMarkdown).toBe(true);
    expect(surface.suppressLegacyProcess).toBe(true);
    expect(surface.suppressLegacyResponse).toBe(true);
    expect(surface.suppressLegacyTurnStatus).toBe(true);
  });

  it("falls back to legacy projected cells when native transcript is missing or empty", () => {
    expect(hasUsableNativeCodexTranscript(message({}))).toBe(false);

    const missing = resolveCodexTranscriptSurface(message({}), fallbackCells);
    expect(missing.mode).toBe("legacy");
    expect(missing.source).toBe("legacy_projection");
    expect(missing.cells).toBe(fallbackCells);
    expect(missing.suppressLegacyProcess).toBe(false);
    expect(missing.suppressLegacyResponse).toBe(false);

    const empty = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [],
      },
    }), fallbackCells);
    expect(empty.mode).toBe("legacy");
    expect(empty.fallbackReason).toBe("native_empty");
  });

  it("does not suppress legacy response text when native transcript has only process cells", () => {
    const surface = resolveCodexTranscriptSurface(message({
      content: "最终回答应该继续显示",
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "assistant-native-process-only",
        cells: [
          {
            id: "native-tool-only",
            kind: "tool_call",
            messageId: "assistant-native-process-only",
            status: "completed",
            tone: "neutral",
            title: "grep_search_tool",
            summary: "未找到匹配项",
          },
        ],
        toolCalls: [],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
    }), fallbackCells);

    expect(surface.mode).toBe("native");
    expect(surface.hasAssistantMarkdown).toBe(false);
    expect(surface.suppressLegacyProcess).toBe(true);
    expect(surface.suppressLegacyResponse).toBe(false);
  });

  it("preserves native terminal lifecycle arrays on the transcript cells", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "native-tool",
            kind: "tool_call",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            title: "命令",
          },
        ],
        toolCalls: [
          {
            toolCallId: "tool_call:op",
            rawOperationId: "op",
            status: "completed",
            title: "命令",
            runtimeKind: "terminal",
            terminalOperationId: "terminal_operation:0",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal_operation:0",
            toolCallId: "tool_call:op",
            terminalId: "terminal:op",
            kind: "ExecCommand",
            status: "completed",
            request: { displayCommand: "npm test", command: ["npm test"], cwd: "" },
            rawOperationId: "op",
          },
        ],
        terminalSessions: [
          {
            terminalId: "terminal:op",
            createdByOperationId: "terminal_operation:0",
            operationIds: ["terminal_operation:0"],
            status: "completed",
          },
        ],
        modelObservations: [
          {
            operationId: "terminal_operation:0",
            toolCallId: "tool_call:op",
            source: "DirectToolCall",
            callItemIds: ["tool_call:op"],
            outputItemIds: ["tool_call:op:output"],
          },
        ],
      },
    }), []);

    expect(surface.cells[0].toolLifecycleModel).toMatchObject({
      toolCalls: [expect.objectContaining({ runtimeKind: "terminal" })],
      terminalOperations: [expect.objectContaining({ operationId: "terminal_operation:0" })],
      terminalSessions: [expect.objectContaining({ terminalId: "terminal:op" })],
      modelObservations: [expect.objectContaining({ source: "DirectToolCall" })],
    });
  });

  it("filters unknown native rollout event kinds before rendering", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "native-tool",
            kind: "tool_call",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            title: "命令",
            operationIds: ["op"],
          },
        ],
        rolloutEvents: [
          {
            id: "native-tool-call-started",
            kind: "ToolCallStarted",
            operationId: "op",
            status: "running",
            title: "native tool",
            runtimeKind: "tool",
          },
          {
            id: "future-event",
            kind: "FutureNativeEvent",
            operationId: "op",
            status: "running",
            title: "future event",
            runtimeKind: "tool",
          },
        ],
      },
    }), []);

    expect(surface.cells[0].rolloutTraceEvents?.map((event) => event.kind)).toEqual(["ToolCallStarted"]);
  });

  it("normalizes native tool lifecycle fields before rendering", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "native-tool",
            kind: "tool_call",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            title: "命令",
          },
        ],
        toolCalls: [
          {
            toolCallId: "tool_call:op",
            rawOperationId: "op",
            status: "future_status",
            title: "future tool",
            runtimeKind: "future_runtime",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal_operation:0",
            toolCallId: "tool_call:op",
            terminalId: "terminal:op",
            kind: "FutureTerminalKind",
            status: "still_future",
            request: { displayCommand: "npm test", command: ["npm test"], cwd: "" },
            rawOperationId: "op",
          },
        ],
        terminalSessions: [
          {
            terminalId: "terminal:op",
            createdByOperationId: "terminal_operation:0",
            operationIds: ["terminal_operation:0"],
            status: "later",
          },
        ],
        modelObservations: [
          {
            operationId: "terminal_operation:0",
            toolCallId: "tool_call:op",
            source: "FutureObservation",
            callItemIds: ["tool_call:op"],
            outputItemIds: ["tool_call:op:output"],
          },
        ],
      },
    }), []);

    expect(surface.cells[0].toolLifecycleModel).toMatchObject({
      toolCalls: [expect.objectContaining({ status: "completed", runtimeKind: "tool" })],
      terminalOperations: [expect.objectContaining({ status: "completed", kind: "ExecCommand" })],
      terminalSessions: [expect.objectContaining({ status: "completed" })],
      modelObservations: [],
    });
  });
});
