import { describe, expect, it } from "vitest";

import type { AgentMessage } from "../../agent-thread/types";
import type { AgentMessageOperation } from "./agentMessageOperations";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import codexTranscriptCellsSource from "./codexTranscriptCells.ts?raw";
import {
  buildCodexTranscriptCells,
  compactCodexTranscriptCellsAcrossMessages,
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

  it("compacts status failed terminal payloads without exposing raw output", () => {
    const rawFailure = JSON.stringify({
      status: "failed",
      terminalSessionId: "sandbox-terminal",
      sessionOpen: false,
      code: "TERMINAL_STDIN_UNAVAILABLE",
      failureClass: "terminal_stdin_unavailable",
      message: "终端会话已结束，不能继续写入。",
      stdout: "const ConfigSummary = () => veryLongInternalSourceCode",
    });
    const cells = buildCodexTranscriptCells(message({ id: "terminal-write-failure" }), {
      operations: [
        {
          id: "op-write-stdin",
          kind: "tool",
          label: "write_stdin",
          status: "failed",
          summary: rawFailure,
          error: rawFailure,
          durationSeconds: null,
        },
      ],
    });

    expect(cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        title: "write_stdin",
        summary: "终端会话已结束",
        failureCount: 1,
        diagnosticSummary: expect.objectContaining({
          reasonCode: "TERMINAL_STDIN_UNAVAILABLE",
          reasonSummary: "终端会话已结束，不能继续写入。",
        }),
      }),
    ]);
    expect(cells[0]?.summary).not.toContain("terminalSessionId");
    expect(cells[0]?.summary).not.toContain("ConfigSummary");
  });

  it("uses failed command operation diagnostics instead of the raw group summary", () => {
    const rawFailure = JSON.stringify({
      status: "failed",
      code: "TERMINAL_STDIN_UNAVAILABLE",
      message: "终端会话已结束，不能继续写入。",
      stdout: "large internal output",
    });
    const timelineItems: AgentMessageTimelineItem[] = [
      {
        id: "failed-write-group",
        kind: "command_group",
        status: "failed",
        title: "write_stdin",
        summary: rawFailure,
        operations: [
          {
            id: "op-failed-write",
            kind: "tool",
            label: "write_stdin",
            status: "failed",
            summary: rawFailure,
            error: rawFailure,
            durationSeconds: null,
          },
        ],
      },
    ];

    const cells = buildCodexTranscriptCells(message({ id: "failed-command-group" }), { timelineItems });

    expect(cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        title: "write_stdin",
        summary: "终端会话已结束",
        operationIds: ["op-failed-write"],
      }),
    ]);
    expect(cells[0]?.summary).not.toContain("{");
    expect(cells[0]?.summary).not.toContain("large internal output");
  });

  it("folds contiguous failures with the same root cause into one high-value row", () => {
    const quotaError = "[工具授权] 当前回合工具调用额度已用尽。请刷新 Agent 工具配置后重试。";
    const operations: AgentMessageOperation[] = [
      {
        id: "op-search",
        kind: "tool",
        label: "搜索",
        status: "failed",
        summary: quotaError,
        error: quotaError,
        durationSeconds: null,
      },
      ...["op-graph-1", "op-graph-2", "op-graph-3"].map((id): AgentMessageOperation => ({
        id,
        kind: "tool",
        label: "代码图谱",
        status: "failed",
        summary: quotaError,
        error: quotaError,
        durationSeconds: null,
      })),
    ];

    const cells = buildCodexTranscriptCells(message({ id: "repeated-tool-quota" }), { operations });

    expect(cells).toEqual([
      expect.objectContaining({
        kind: "error_notice",
        title: "工具调用受限",
        summary: "本回合工具调用额度已用尽",
        failureCount: 4,
        operationIds: ["op-search", "op-graph-1", "op-graph-2", "op-graph-3"],
        diagnosticSummary: expect.objectContaining({
          reasonCode: "tool_quota_exhausted",
        }),
      }),
    ]);
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

  it("folds a terminal continuation back into its originating command row", () => {
    const cells = buildCodexTranscriptCells(message({ id: "terminal-continuation" }), {
      operations: [
        {
          id: "op-exec",
          kind: "tool",
          label: "exec_command",
          rawLabel: "exec_command",
          status: "running",
          summary: "npm test",
          terminalSessionId: "sandbox-a",
          durationSeconds: null,
        },
        {
          id: "op-late-poll",
          kind: "tool",
          label: "write_stdin",
          rawLabel: "write_stdin",
          status: "completed",
          summary: "12 passed",
          resultPreview: "12 passed",
          terminalSessionId: "sandbox-a",
          exitCode: 0,
          durationSeconds: null,
        },
      ],
    });

    expect(cells).toHaveLength(1);
    expect(cells[0]).toMatchObject({
      kind: "tool_call",
      title: "exec_command",
      status: "completed",
      summary: "12 passed",
      operationIds: ["op-exec", "op-late-poll"],
    });
  });

  it("folds a terminal continuation across assistant message boundaries", () => {
    const execCells = buildCodexTranscriptCells(message({ id: "terminal-command-message" }), {
      operations: [
        {
          id: "op-exec",
          kind: "tool",
          label: "exec_command",
          rawLabel: "exec_command",
          status: "running",
          summary: "ping -n 3 127.0.0.1",
          terminalSessionId: "sandbox-cross-message",
          durationSeconds: null,
        },
      ],
    });
    const continuationCells = buildCodexTranscriptCells(message({ id: "terminal-poll-message" }), {
      operations: [
        {
          id: "op-late-poll",
          kind: "tool",
          label: "write_stdin",
          rawLabel: "write_stdin",
          status: "completed",
          summary: "command finished",
          resultPreview: "command finished",
          terminalSessionId: "sandbox-cross-message",
          exitCode: 7,
          durationSeconds: null,
        },
      ],
    });

    const compacted = compactCodexTranscriptCellsAcrossMessages([
      { messageId: "terminal-command-message", cells: execCells },
      { messageId: "terminal-poll-message", cells: continuationCells },
    ]);

    expect(compacted.get("terminal-command-message")).toEqual([
      expect.objectContaining({
        kind: "tool_call",
        title: "exec_command",
        status: "completed",
        tone: "warning",
        summary: "command finished",
        operationIds: ["op-exec", "op-late-poll"],
      }),
    ]);
    expect(compacted.get("terminal-poll-message")).toEqual([]);
  });

  it("does not fold a terminal continuation across a user-message boundary", () => {
    const execCells = buildCodexTranscriptCells(message({ id: "terminal-command-before-user" }), {
      operations: [
        {
          id: "op-exec",
          kind: "tool",
          label: "exec_command",
          rawLabel: "exec_command",
          status: "running",
          summary: "ping -n 3 127.0.0.1",
          terminalSessionId: "sandbox-user-boundary",
          durationSeconds: null,
        },
      ],
    });
    const continuationCells = buildCodexTranscriptCells(message({ id: "terminal-poll-after-user" }), {
      operations: [
        {
          id: "op-late-poll",
          kind: "tool",
          label: "write_stdin",
          rawLabel: "write_stdin",
          status: "completed",
          summary: "command finished",
          terminalSessionId: "sandbox-user-boundary",
          exitCode: 0,
          durationSeconds: null,
        },
      ],
    });

    const compacted = compactCodexTranscriptCellsAcrossMessages([
      { messageId: "terminal-command-before-user", cells: execCells },
      { messageId: "user-message", cells: [], barrier: true },
      { messageId: "terminal-poll-after-user", cells: continuationCells },
    ]);

    expect(compacted.get("terminal-command-before-user")).toHaveLength(1);
    expect(compacted.get("terminal-poll-after-user")).toHaveLength(1);
  });

  it("absorbs a legacy closed-terminal write failure into the command row", () => {
    const lateWriteFailure = JSON.stringify({
      status: "failed",
      terminalSessionId: "sandbox-a",
      sessionOpen: false,
      code: "TERMINAL_STDIN_UNAVAILABLE",
      message: "terminal session already ended",
    });
    const cells = buildCodexTranscriptCells(message({ id: "terminal-legacy-continuation" }), {
      operations: [
        {
          id: "op-exec",
          kind: "tool",
          label: "exec_command",
          rawLabel: "exec_command",
          status: "done",
          summary: "npm test",
          terminalSessionId: "sandbox-a",
          durationSeconds: null,
        },
        {
          id: "op-late-poll",
          kind: "tool",
          label: "write_stdin",
          rawLabel: "write_stdin",
          status: "failed",
          summary: lateWriteFailure,
          error: lateWriteFailure,
          terminalSessionId: "sandbox-a",
          sessionOpen: false,
          durationSeconds: null,
        },
      ],
    });

    expect(cells).toHaveLength(1);
    expect(cells[0]).toMatchObject({
      kind: "tool_call",
      title: "exec_command",
      status: "completed",
      operationIds: ["op-exec", "op-late-poll"],
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
