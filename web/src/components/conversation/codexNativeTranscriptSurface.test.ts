import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  hasUsableNativeCodexTranscript,
  resolveCodexTranscriptSurface,
} from "./codexNativeTranscriptSurface";

const projectedCells: CodexTranscriptCell[] = [
  {
    id: "projected-tool",
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "projected",
  },
];

function message(patch: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "projected answer",
    timestamp: "2026-07-07T10:45:00Z",
    ...patch,
  };
}

describe("codexNativeTranscriptSurface", () => {
  it("prefers backend native transcript cells over projected transcript cells", () => {
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
    }), projectedCells);

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
    expect(surface.suppressProjectedProcess).toBe(true);
    expect(surface.suppressProjectedResponse).toBe(true);
    expect(surface.suppressProjectedTurnStatus).toBe(true);
  });

  it("normalizes legacy markdown and preserves terminal error metadata at the native boundary", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "legacy-answer",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            markdown: "legacy snapshot answer",
            channel: "answer",
            phase: "final_answer",
          } as never,
          {
            id: "terminal-error",
            kind: "error_notice",
            messageId: "message-1",
            status: "failed",
            tone: "error",
            text: "sanitized error",
            phase: "turn_failed",
            terminal: true,
            provisional: false,
            diagnosticSummary: { httpStatus: 502, reasonCode: "upstream_unavailable" },
          },
        ],
      },
    }), []);

    expect(surface.cells[0]).toMatchObject({
      text: "legacy snapshot answer",
      channel: "answer",
      phase: "final_answer",
    });
    expect(surface.cells[1]).toMatchObject({
      phase: "turn_failed",
      terminal: true,
      provisional: false,
      diagnosticSummary: { httpStatus: 502, reasonCode: "upstream_unavailable" },
    });
    expect(surface.suppressProjectedError).toBe(true);
    expect(surface.suppressProjectedResponse).toBe(true);
  });

  it("compacts and folds repeated raw native tool failures at the transcript boundary", () => {
    const quotaFailure = "[工具授权] 当前回合工具调用额度已用尽。请刷新 Agent 工具配置后重试。";
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "assistant-native-tool-failures",
        cells: [
          {
            id: "native-search-failure",
            kind: "error_notice",
            messageId: "assistant-native-tool-failures",
            status: "failed",
            tone: "error",
            title: "搜索",
            text: quotaFailure,
            summary: quotaFailure,
            operationIds: ["op-search"],
          },
          ...["op-graph-1", "op-graph-2", "op-graph-3"].map((operationId) => ({
            id: `native-${operationId}`,
            kind: "error_notice" as const,
            messageId: "assistant-native-tool-failures",
            status: "failed",
            tone: "error",
            title: "代码图谱",
            text: quotaFailure,
            summary: quotaFailure,
            operationIds: [operationId],
          })),
        ],
      },
    }), []);

    expect(surface.cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        title: "工具调用受限",
        text: undefined,
        summary: "本回合工具调用额度已用尽",
        failureCount: 4,
        operationIds: ["op-search", "op-graph-1", "op-graph-2", "op-graph-3"],
        diagnosticSummary: expect.objectContaining({
          reasonCode: "tool_quota_exhausted",
        }),
      }),
    ]);
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
    }), projectedCells);

    expect(surface.mode).toBe("native");
    expect(surface.cells.map((cell) => cell.id)).toEqual(["native-answer"]);
    expect(surface.hasAssistantMarkdown).toBe(true);
    expect(surface.suppressProjectedResponse).toBe(true);
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
    }), projectedCells);

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
      projectedCellCount: 1,
    });
    expect(surface.suppressProjectedResponse).toBe(false);
  });

  it("records projection gaps instead of falling back to projected cells when native transcript is missing or empty", () => {
    expect(hasUsableNativeCodexTranscript(message({}))).toBe(false);

    const missing = resolveCodexTranscriptSurface(message({}), projectedCells);
    expect(missing.mode).toBe("empty");
    expect(missing.source).toBe("none");
    expect(missing.cells).toEqual([]);
    expect(missing.suppressProjectedProcess).toBe(false);
    expect(missing.suppressProjectedResponse).toBe(false);
    expect(missing.projectionGap).toEqual({
      reason: "native_missing",
      projectedCellCount: 1,
    });

    const empty = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [],
      },
    }), projectedCells);
    expect(empty.mode).toBe("empty");
    expect(empty.source).toBe("none");
    expect(empty.cells).toEqual([]);
    expect(empty.projectionGap).toEqual({
      reason: "native_empty",
      projectedCellCount: 1,
    });
  });

  it("does not suppress projected response text when native transcript has only process cells", () => {
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
    }), projectedCells);

    expect(surface.mode).toBe("native");
    expect(surface.hasAssistantMarkdown).toBe(false);
    expect(surface.suppressProjectedProcess).toBe(true);
    expect(surface.suppressProjectedResponse).toBe(false);
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

describe("native transcript semantic tool labels", () => {
  it("projects a cli protocol title from its terminal command and keeps the raw name diagnostic", () => {
    const surface = resolveCodexTranscriptSurface(message({
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "native-cli-label",
        cells: [
          {
            id: "native-cli-tool",
            kind: "tool_call",
            messageId: "native-cli-label",
            status: "completed",
            tone: "neutral",
            title: "cli_tool",
            summary: "运行前端聚焦测试",
            operationIds: ["native-cli-operation"],
          },
        ],
        toolCalls: [
          {
            toolCallId: "tool_call:native-cli-operation",
            rawOperationId: "native-cli-operation",
            status: "completed",
            title: "cli_tool",
            runtimeKind: "terminal",
            terminalOperationId: "terminal_operation:0",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal_operation:0",
            toolCallId: "tool_call:native-cli-operation",
            terminalId: "terminal:native-cli-operation",
            kind: "ExecCommand",
            status: "completed",
            request: {
              displayCommand: "npx vitest run conversationToolSemanticLabel.test.ts",
              command: ["npx vitest run conversationToolSemanticLabel.test.ts"],
              cwd: "",
            },
            rawOperationId: "native-cli-operation",
          },
        ],
      },
    }), []);

    expect(surface.cells[0]).toMatchObject({
      title: "运行测试",
      diagnosticSummary: { rawToolName: "cli_tool" },
    });
  });
});
