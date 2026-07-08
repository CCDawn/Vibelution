import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  hasUsableNativeCodexTranscript,
  resolveCodexTranscriptSurface,
} from "./codexNativeTranscriptSurface";

const legacyProjectionCells: CodexTranscriptCell[] = [
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
  it("prefers backend native transcript cells over legacy projection cells", () => {
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
    }), legacyProjectionCells);

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

  it("removes internal runtime status cells from native transcripts while keeping the answer", () => {
    const surface = resolveCodexTranscriptSurface(message({
      content: "模型连接正在重试...\n第 1/5 次；原因：server_error。本轮仍在继续，请不要重复提交。\n\n本轮已按请求停止。",
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "assistant-native-retry",
        cells: [
          {
            id: "status-context-prepare",
            kind: "status",
            messageId: "assistant-native-retry",
            status: "completed",
            tone: "neutral",
            title: "context_prepare",
            summary: "正在准备对话上下文... 正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
          },
          {
            id: "status-model-request",
            kind: "status",
            messageId: "assistant-native-retry",
            status: "completed",
            tone: "neutral",
            title: "model_request",
            summary: "正在请求模型，等待首个响应片段... 上下文已组装完成，正在进入 LLM 调用。",
          },
          {
            id: "status-retrying",
            kind: "status",
            messageId: "assistant-native-retry",
            status: "completed",
            tone: "warning",
            title: "retrying",
            summary: "第 1/5 次；原因：server_error。",
          },
          {
            id: "native-answer",
            kind: "assistant_markdown",
            messageId: "assistant-native-retry",
            status: "completed",
            tone: "neutral",
            text: "本轮已按请求停止。",
          },
        ],
      },
    }), legacyProjectionCells);

    expect(surface.mode).toBe("native");
    expect(surface.cells.map((cell) => cell.id)).toEqual(["native-answer"]);
    expect(surface.hasAssistantMarkdown).toBe(true);
    expect(surface.suppressLegacyResponse).toBe(true);
  });

  it("keeps native error status cells visible", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "assistant-native-error",
        cells: [
          {
            id: "status-error",
            kind: "status",
            messageId: "assistant-native-error",
            status: "failed",
            tone: "error",
            title: "model_request",
            summary: "模型请求失败：server_error",
          },
        ],
      },
    }), []);

    expect(surface.cells.map((cell) => cell.id)).toEqual(["status-error"]);
  });

  it("ignores native assistant transcript cells attached to user messages", () => {
    const surface = resolveCodexTranscriptSurface(message({
      role: "user",
      content: "你好",
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "message-1-assistant-markdown",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            text: "你好",
          },
        ],
      },
    }), legacyProjectionCells);

    expect(hasUsableNativeCodexTranscript(message({
      role: "user",
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "message-1-assistant-markdown",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            text: "你好",
          },
        ],
      },
    }))).toBe(false);
    expect(surface.mode).toBe("empty");
    expect(surface.source).toBe("none");
    expect(surface.cells).toEqual([]);
    expect(surface.projectionGap).toEqual({
      reason: "native_unusable",
      legacyCellCount: 1,
    });
    expect(surface.suppressLegacyResponse).toBe(false);
  });

  it("records projection gaps instead of falling back to legacy projected cells when native transcript is missing or empty", () => {
    expect(hasUsableNativeCodexTranscript(message({}))).toBe(false);

    const missing = resolveCodexTranscriptSurface(message({}), legacyProjectionCells);
    expect(missing.mode).toBe("empty");
    expect(missing.source).toBe("none");
    expect(missing.cells).toEqual([]);
    expect(missing.suppressLegacyProcess).toBe(false);
    expect(missing.suppressLegacyResponse).toBe(false);
    expect(missing.projectionGap).toEqual({
      reason: "native_missing",
      legacyCellCount: 1,
    });

    const empty = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [],
      },
    }), legacyProjectionCells);
    expect(empty.mode).toBe("empty");
    expect(empty.source).toBe("none");
    expect(empty.cells).toEqual([]);
    expect(empty.projectionGap).toEqual({
      reason: "native_empty",
      legacyCellCount: 1,
    });
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
    }), legacyProjectionCells);

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
