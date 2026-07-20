import { describe, expect, it } from "vitest";

import type { AgentMessage } from "../../agent-thread/types";
import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import codexTranscriptCellsSource from "./codexTranscriptCells.ts?raw";
import {
  buildCodexTranscriptCells,
  type CodexTranscriptCell,
  type CodexTranscriptCellKind,
} from "./codexTranscriptCells";

function message(overrides: Partial<AgentMessage>): AgentMessage {
  return {
    id: "message-1",
    role: "assistant",
    createdAt: "2026-07-06T10:00:00Z",
    streaming: false,
    source: { kind: "conversation-message", id: "message-1" },
    parts: [],
    ...overrides,
  };
}

describe("codexTranscriptCells", () => {
  it("exports the Codex-like transcript cell contract", () => {
    const kind: CodexTranscriptCellKind = "assistant_markdown";
    const cell: CodexTranscriptCell = {
      id: "cell-1",
      kind,
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      text: "ok",
    };

    expect(cell.kind).toBe("assistant_markdown");
    expect(codexTranscriptCellsSource).toContain("export type CodexTranscriptCellKind");
    expect(codexTranscriptCellsSource).toContain("export type CodexTranscriptCell =");
    expect(codexTranscriptCellsSource).toContain("export function buildCodexTranscriptCells");
    expect(codexTranscriptCellsSource).toContain('from "./codexRolloutTrace"');
    expect(codexTranscriptCellsSource).toContain('from "./codexToolLifecycleModel"');
    expect(codexTranscriptCellsSource).toContain("rolloutTraceEvents?:");
    expect(codexTranscriptCellsSource).toContain("toolLifecycleModel?:");
  });

  it("maps user text into one user cell", () => {
    const cells = buildCodexTranscriptCells(message({
      id: "user-message",
      role: "user",
      parts: [
        { id: "user-text-1", type: "text", channel: "user", text: "先检查对话布局。" },
        { id: "user-text-2", type: "text", channel: "user", text: "再收口 adapter。" },
      ],
    }));

    expect(cells).toEqual([
      expect.objectContaining({
        id: "user-message-user",
        kind: "user",
        messageId: "user-message",
        status: "completed",
        tone: "neutral",
        text: "先检查对话布局。\n\n再收口 adapter。",
      }),
    ]);
  });

  it("maps assistant answers and reasoning summaries from timeline items", () => {
    const timelineItems: AgentMessageTimelineItem[] = [
      {
        id: "thought-1",
        kind: "thought",
        status: "completed",
        text: "我先定位渲染分层。",
        preview: "我先定位渲染分层。",
        defaultExpanded: false,
        sourceOperationIds: ["op-thought-1"],
      },
      {
        id: "answer-1",
        kind: "assistant_text",
        status: "completed",
        text: "已经完成第一阶段对齐。",
      },
    ];

    const cells = buildCodexTranscriptCells(message({ id: "assistant-message" }), { timelineItems });

    expect(cells.map((cell) => cell.kind)).toEqual(["reasoning_summary", "assistant_markdown"]);
    expect(cells[0]).toMatchObject({
      id: "assistant-message-thought-1",
      kind: "reasoning_summary",
      messageId: "assistant-message",
      status: "completed",
      tone: "neutral",
      text: "我先定位渲染分层。",
      summary: "我先定位渲染分层。",
      operationIds: ["op-thought-1"],
      sourceItemId: "thought-1",
    });
    expect(cells[1]).toMatchObject({
      id: "assistant-message-answer-1",
      kind: "assistant_markdown",
      status: "completed",
      tone: "neutral",
      text: "已经完成第一阶段对齐。",
      sourceItemId: "answer-1",
    });
  });

  it("maps tool, degraded, and failed operation cells without changing backend DTOs", () => {
    const operations: AgentMessageOperation[] = [
      {
        id: "op-search",
        kind: "tool",
        label: "搜索",
        status: "done",
        summary: "搜索 ConversationView",
        durationSeconds: null,
      },
      {
        id: "op-status",
        kind: "status",
        label: "准备上下文",
        status: "running",
        summary: "读取会话、Agent 与工具权限",
        durationSeconds: null,
      },
      {
        id: "op-partial",
        kind: "tool",
        label: "读取文件",
        status: "partial",
        summary: "只返回部分输出",
        durationSeconds: null,
      },
      {
        id: "op-failed",
        kind: "tool",
        label: "命令",
        status: "failed",
        summary: "命令失败",
        error: "Exit code 1",
        durationSeconds: null,
      },
    ];

    const cells = buildCodexTranscriptCells(message({ id: "operation-message" }), { operations });

    expect(cells.map((cell) => cell.kind)).toEqual(["tool_call", "tool_call", "error_notice"]);
    expect(cells[0]).toMatchObject({
      kind: "tool_call",
      status: "completed",
      tone: "neutral",
      title: "搜索",
      summary: "搜索 ConversationView",
      operationIds: ["op-search"],
    });
    expect(rolloutTraceEvents(cells[0]).map((event) => event.kind)).toEqual([
      "ToolCallStarted",
      "RuntimeStarted",
      "RuntimeEnded",
      "ToolCallEnded",
    ]);
    expect(cells[1]).toMatchObject({
      kind: "tool_call",
      status: "degraded",
      tone: "warning",
    });
    expect(rolloutTraceEvents(cells[1])).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: "RuntimeEnded",
        operationId: "op-partial",
        status: "degraded",
      }),
    ]));
    expect(cells[2]).toMatchObject({
      kind: "error_notice",
      status: "failed",
      tone: "error",
      summary: "Exit code 1",
    });
    expect(rolloutTraceEvents(cells[2])).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: "RuntimeEnded",
        operationId: "op-failed",
        status: "failed",
        error: "Exit code 1",
      }),
    ]));
  });

  it("projects structured tool failures into a compact summary and safe diagnostics", () => {
    const rawFailure = JSON.stringify({
      status: "error",
      mode: "inspect",
      error: "target_not_indexed",
      message: "inspect 目标文件 `tools` 未在代码图谱索引中。请用 refresh=true 重试。",
      target: { filePath: "tools" },
      index: { fresh: false, updatedAt: "2026-07-14T05:43:01Z", fileCount: 1700 },
    });
    const cells = buildCodexTranscriptCells(message({ id: "structured-tool-failure" }), {
      operations: [
        {
          id: "op-code-graph",
          kind: "tool",
          label: "代码图谱",
          status: "failed",
          summary: "执行失败",
          error: rawFailure,
          durationSeconds: null,
        },
      ],
    });

    expect(cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        title: "代码图谱",
        summary: "索引未就绪",
        diagnosticSummary: {
          reasonCode: "target_not_indexed",
          reasonSummary: "inspect 目标文件 `tools` 未在代码图谱索引中。请用 refresh=true 重试。",
          reasonDetail: "目标：tools\n建议：刷新索引后重试",
        },
      }),
    ]);
    expect(cells[0]?.summary).not.toContain("{");
  });

  it("filters internal runtime status operation cells from legacy transcript projections", () => {
    const cells = buildCodexTranscriptCells(message({ id: "legacy-internal-status" }), {
      operations: [
        {
          id: "op-context-prepare",
          kind: "status",
          label: "context_prepare",
          status: "done",
          summary: "正在准备对话上下文... 正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
          durationSeconds: null,
        },
        {
          id: "op-retrying",
          kind: "status",
          label: "retrying",
          status: "done",
          summary: "第 1/5 次；原因：server_error。",
          durationSeconds: null,
        },
      ],
    });

    expect(cells).toEqual([]);
  });

  it("attaches the Codex-like lifecycle model to terminal tool cells", () => {
    const cells = buildCodexTranscriptCells(message({ id: "terminal-message" }), {
      operations: [
        {
          id: "op-command",
          kind: "tool",
          label: "命令",
          rawLabel: "cli_tool",
          terminalSessionId: "op-command",
          status: "done",
          summary: "npm --prefix web run test",
          durationSeconds: 1.5,
        },
      ],
    });

    expect(lifecycleModel(cells[0])).toMatchObject({
      toolCalls: [
        expect.objectContaining({
          toolCallId: "tool_call:op-command",
          terminalOperationId: "terminal_operation:0",
          runtimeKind: "terminal",
        }),
      ],
      terminalOperations: [
        expect.objectContaining({
          operationId: "terminal_operation:0",
          terminalId: "terminal:op-command",
          request: expect.objectContaining({
            displayCommand: "npm --prefix web run test",
          }),
        }),
      ],
      terminalSessions: [
        expect.objectContaining({
          terminalId: "terminal:op-command",
          operationIds: ["terminal_operation:0"],
        }),
      ],
      modelObservations: [
        expect.objectContaining({
          source: "DirectToolCall",
          toolCallId: "tool_call:op-command",
        }),
      ],
    });
  });

  it("maps command groups to tool_call cells and preserves failed groups as error notices", () => {
    const timelineItems: AgentMessageTimelineItem[] = [
      {
        id: "command-group-ok",
        kind: "command_group",
        status: "completed",
        title: "已运行 2 条命令",
        summary: "搜索；读取",
        operations: [
          {
            id: "op-1",
            kind: "tool",
            label: "搜索",
            status: "done",
            summary: "搜索",
            durationSeconds: null,
          },
          {
            id: "op-2",
            kind: "tool",
            label: "读取",
            status: "done",
            summary: "读取",
            durationSeconds: null,
          },
        ],
      },
      {
        id: "command-group-failed",
        kind: "command_group",
        status: "failed",
        title: "已运行 1 条命令",
        summary: "命令失败",
        operations: [
          {
            id: "op-3",
            kind: "tool",
            label: "命令",
            status: "failed",
            summary: "命令失败",
            durationSeconds: null,
          },
        ],
      },
    ];

    const cells = buildCodexTranscriptCells(message({ id: "command-message" }), { timelineItems });

    expect(cells.map((cell) => cell.kind)).toEqual(["tool_call", "error_notice"]);
    expect(cells[0]).toMatchObject({
      kind: "tool_call",
      status: "completed",
      tone: "neutral",
      operationIds: ["op-1", "op-2"],
    });
    expect(rolloutTraceEvents(cells[0])).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: "ToolCallStarted",
        operationId: "op-1",
      }),
      expect.objectContaining({
        kind: "ToolCallEnded",
        operationId: "op-2",
        status: "completed",
      }),
    ]));
    expect(cells[1]).toMatchObject({
      kind: "error_notice",
      status: "failed",
      tone: "error",
      operationIds: ["op-3"],
    });
    expect(rolloutTraceEvents(cells[1])).toEqual(expect.arrayContaining([
      expect.objectContaining({
        kind: "RuntimeEnded",
        operationId: "op-3",
        status: "failed",
      }),
    ]));
  });

  it("adds a stream tail when an assistant turn is still streaming without final answer text", () => {
    const cells = buildCodexTranscriptCells(message({
      id: "streaming-message",
      streaming: true,
      parts: [
        {
          id: "thought-running",
          type: "thought",
          status: "running",
          text: "还在读取上下文。",
        },
      ],
    }), {
      operations: [
        {
          id: "op-running",
          kind: "tool",
          label: "读取文件",
          status: "running",
          summary: "读取 agentMessageTimeline.ts",
          durationSeconds: null,
        },
      ],
    });

    expect(cells.at(-1)).toMatchObject({
      id: "streaming-message-stream-tail",
      kind: "stream_tail",
      messageId: "streaming-message",
      status: "running",
      tone: "running",
    });
  });
});

function rolloutTraceEvents(cell: CodexTranscriptCell) {
  return (
    cell as CodexTranscriptCell & {
      rolloutTraceEvents?: Array<{
        kind: string;
        operationId: string;
        status: string;
        error?: string;
      }>;
    }
  ).rolloutTraceEvents ?? [];
}

function lifecycleModel(cell: CodexTranscriptCell) {
  return (
    cell as CodexTranscriptCell & {
      toolLifecycleModel?: unknown;
    }
  ).toolLifecycleModel;
}
