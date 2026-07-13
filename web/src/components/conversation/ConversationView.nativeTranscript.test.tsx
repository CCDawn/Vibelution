import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

function renderConversation(messages: ConversationMessage[], processDisplayMode: "answer" | "trace" = "trace") {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={messages}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        processDisplayMode={processDisplayMode}
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onStop={() => undefined}
        onClear={() => undefined}
        onJumpToLatest={() => undefined}
        onCreateNewSession={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView native Codex transcript surface", () => {
  it("hides internal runtime process when a native transcript owns the final answer", () => {
    const answer = "你好，我在。";
    const html = renderConversation([
      {
        id: "user-message",
        role: "user",
        content: "你好",
        timestamp: "2026-07-08T15:52:32Z",
      },
      {
        id: "assistant-native-chat-turn",
        role: "assistant",
        content: answer,
        timestamp: "2026-07-08T15:53:00Z",
        feedbackEvents: [
          { sequence: 1, kind: "status", status: "done", name: "context_prepare", summary: "正在准备对话上下文..." },
          { sequence: 2, kind: "status", status: "done", name: "agent_prepare", summary: "正在唤起对话 Agent..." },
          { sequence: 3, kind: "status", status: "done", name: "model_request", summary: "正在请求模型，等待首个响应片段..." },
          { sequence: 4, kind: "status", status: "done", name: "model_thinking", summary: "正在思考中，等待模型输出..." },
        ],
        timelineItems: [
          {
            id: "assistant-native-chat-turn-timeline-response",
            kind: "assistant_text",
            status: "completed",
            text: answer,
          },
        ],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-chat-turn",
          cells: [
            {
              id: "assistant-native-chat-turn-answer",
              kind: "assistant_markdown",
              messageId: "assistant-native-chat-turn",
              status: "completed",
              tone: "neutral",
              text: answer,
            },
          ],
        },
      },
    ], "answer");

    expect(html.match(/你好，我在。/g)).toHaveLength(1);
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
    expect(html).not.toContain('data-agent-process-kind="timeline"');
    expect(html).not.toContain("准备上下文");
    expect(html).not.toContain("绑定 Agent");
    expect(html).not.toContain("请求模型");
    expect(html).not.toContain("模型思考");
    expect(html).not.toContain("正在准备对话上下文...");
    expect(html).not.toContain("正在唤起对话 Agent...");
    expect(html).not.toContain("正在请求模型，等待首个响应片段...");
    expect(html).not.toContain("正在思考中，等待模型输出...");
  });

  it("renders no-final-answer native assistant markdown as a turn status instead of an empty row", () => {
    const statusText = "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。";
    const html = renderConversation([
      {
        id: "user-continue",
        role: "user",
        content: "继续",
        timestamp: "2026-07-09T17:38:16Z",
      },
      {
        id: "assistant-native-needs-continue",
        role: "assistant",
        content: statusText,
        timestamp: "2026-07-09T17:38:35Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-needs-continue",
          cells: [
            {
              id: "assistant-native-needs-continue-status",
              kind: "assistant_markdown",
              messageId: "assistant-native-needs-continue",
              status: "completed",
              tone: "neutral",
              text: statusText,
            },
          ],
        },
      },
    ]);

    expect(html).toContain(statusText);
    expect(html).toContain("状态");
    expect(html).not.toContain('data-codex-transcript-cell-kind="assistant_markdown"');
    expect(html).not.toContain("responseSection");
  });

  it("renders a canonical terminal error once without a legacy response or turn notice", () => {
    const html = renderConversation([
      {
        id: "message-error",
        role: "assistant",
        content: "上游服务暂不可用。",
        timestamp: "2026-07-13T00:00:00.000Z",
        metadata: { kind: "turn_error", errorType: "provider_upstream_error", httpStatus: 502 },
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-error",
          cells: [
            {
              id: "error",
              kind: "error_notice",
              messageId: "message-error",
              status: "failed",
              tone: "error",
              phase: "turn_failed",
              terminal: true,
              text: "上游服务暂不可用。",
              diagnosticSummary: { httpStatus: 502, reasonCode: "upstream_unavailable" },
            },
          ],
        },
      },
    ]);

    expect(html.match(/上游服务暂不可用。/g)).toHaveLength(1);
    expect(html).toContain('data-codex-transcript-cell-kind="error_notice"');
    expect(html).not.toContain("运行提示");
    expect(html).toContain("诊断详情");
    expect(html).toContain("upstream_unavailable");
    expect(html).not.toContain('open=""');
    expect(html).not.toContain("responseSection");
  });

  it("keeps commentary, tool, and final answer in canonical DOM order with tool details closed", () => {
    const html = renderConversation([
      {
        id: "message-chain",
        role: "assistant",
        content: "legacy duplicate final",
        timestamp: "2026-07-13T00:00:00.000Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-chain",
          cells: [
            {
              id: "commentary",
              kind: "assistant_markdown",
              messageId: "message-chain",
              status: "completed",
              tone: "neutral",
              channel: "commentary",
              phase: "commentary",
              text: "我先检查文件。",
            },
            {
              id: "tool",
              kind: "tool_call",
              messageId: "message-chain",
              status: "completed",
              tone: "neutral",
              channel: "tool",
              phase: "tool_call",
              title: "read_file",
              operationIds: ["read-file-op"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "tool_call:read-file-op",
                    rawOperationId: "read-file-op",
                    status: "completed",
                    title: "read_file",
                    rawToolName: "read_file",
                    runtimeKind: "tool",
                    resultPreview: "file loaded",
                  },
                ],
                terminalOperations: [],
                terminalSessions: [],
                modelObservations: [],
              },
            },
            {
              id: "final",
              kind: "assistant_markdown",
              messageId: "message-chain",
              status: "completed",
              tone: "neutral",
              channel: "answer",
              phase: "final_answer",
              terminal: true,
              text: "检查完成。",
            },
          ],
        },
      },
    ]);

    const commentaryIndex = html.indexOf("我先检查文件。");
    const toolIndex = html.indexOf("read_file");
    const finalIndex = html.indexOf("检查完成。");
    expect(commentaryIndex).toBeGreaterThan(-1);
    expect(toolIndex).toBeGreaterThan(commentaryIndex);
    expect(finalIndex).toBeGreaterThan(toolIndex);
    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).not.toContain('open=""');
    expect(html).not.toContain("legacy duplicate final");
    expect(html).toContain("codexTranscriptCommentaryCell");
    expect(html).toContain("codexTranscriptFinalCell");
  });

  it("renders native transcript as the primary assistant surface without duplicating legacy process or response", () => {
    const html = renderConversation([
      {
        id: "assistant-native",
        role: "assistant",
        content: "legacy response should not duplicate",
        timestamp: "2026-07-07T11:00:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "legacy_tool",
            summary: "legacy process should not render",
          },
        ],
        timelineItems: [
          {
            id: "legacy-operation",
            kind: "operation",
            status: "completed",
            title: "legacy_tool",
            summary: "legacy process should not render",
            operationIds: ["assistant-native-feedback-1"],
          },
        ],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native",
          cells: [
            {
              id: "native-tool",
              kind: "tool_call",
              messageId: "assistant-native",
              status: "completed",
              tone: "neutral",
              title: "native_tool",
              summary: "native process renders",
            },
            {
              id: "native-answer",
              kind: "assistant_markdown",
              messageId: "assistant-native",
              status: "completed",
              tone: "neutral",
              text: "native answer renders",
            },
          ],
        },
      },
    ]);

    expect(html).toContain('data-codex-transcript-surface="true"');
    expect(html).toContain('data-codex-transcript-cell-kind="tool_call"');
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
    expect(html).toContain("native_tool");
    expect(html).not.toContain("native process renders");
    expect(html).toContain("native answer renders");
    expect(html).not.toContain("legacy process should not render");
    expect(html).not.toContain("legacy response should not duplicate");
    expect(html).not.toContain("data-agent-process-kind");
    expect(html).not.toContain("responseSection");
  });

  it("does not render internal runtime status cells from native transcripts", () => {
    const html = renderConversation([
      {
        id: "assistant-native-status-noise",
        role: "assistant",
        content: "模型连接正在重试...\n第 1/5 次；原因：server_error。本轮仍在继续，请不要重复提交。\n\n本轮已按请求停止。",
        timestamp: "2026-07-08T17:01:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-status-noise",
          cells: [
            {
              id: "status-context-prepare",
              kind: "status",
              messageId: "assistant-native-status-noise",
              status: "completed",
              tone: "neutral",
              title: "context_prepare",
              summary: "正在准备对话上下文... 正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
            },
            {
              id: "status-retrying",
              kind: "status",
              messageId: "assistant-native-status-noise",
              status: "completed",
              tone: "warning",
              title: "retrying",
              summary: "第 1/5 次；原因：server_error。",
            },
            {
              id: "native-answer",
              kind: "assistant_markdown",
              messageId: "assistant-native-status-noise",
              status: "completed",
              tone: "neutral",
              text: "本轮已按请求停止。",
            },
          ],
        },
      },
    ]);

    expect(html).toContain('data-codex-transcript-surface="true"');
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
    expect(html).toContain("本轮已按请求停止。");
    expect(html).not.toContain("context_prepare");
    expect(html).not.toContain("retrying");
    expect(html).not.toContain("正在准备对话上下文");
    expect(html).not.toContain("模型连接正在重试");
  });

  it("does not render internal pipeline text when native transcripts carry it as assistant markdown", () => {
    const statusText = "context_prepare\n正在准备对话上下文...\n\nagent_prepare\n正在唤起对话 agent...\n\nmodel_request\n正在请求模型，等待首个响应片段...\n\nretrying\n模型连接正在重试...\n第 1/5 次；原因：server_error。本轮仍在继续，请不要重复提交。";
    const html = renderConversation([
      {
        id: "user-message",
        role: "user",
        content: "你好",
        timestamp: "2026-07-08T17:01:00Z",
      },
      {
        id: "assistant-native-status-markdown",
        role: "assistant",
        content: statusText,
        timestamp: "2026-07-08T17:01:05Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-status-markdown",
          cells: [
            {
              id: "native-status-markdown",
              kind: "assistant_markdown",
              messageId: "assistant-native-status-markdown",
              status: "completed",
              tone: "neutral",
              text: statusText,
            },
          ],
        },
      },
    ]);

    expect(html).toContain("你好");
    expect(html).not.toContain("context_prepare");
    expect(html).not.toContain("agent_prepare");
    expect(html).not.toContain("model_request");
    expect(html).not.toContain("retrying");
    expect(html).not.toContain("正在准备对话上下文");
    expect(html).not.toContain("模型连接正在重试");
    expect(html).not.toContain('data-codex-transcript-cell-kind="assistant_markdown"');
  });

  it("does not render stale native assistant transcript cells on user messages", () => {
    const html = renderConversation([
      {
        id: "user-native-stale",
        role: "user",
        content: "用户消息不应重复显示",
        timestamp: "2026-07-07T11:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "user-native-stale",
          cells: [
            {
              id: "user-native-stale-assistant-markdown",
              kind: "assistant_markdown",
              messageId: "user-native-stale",
              status: "completed",
              tone: "neutral",
              text: "用户消息不应重复显示",
            },
          ],
        },
      },
    ]);

    expect(html.match(/用户消息不应重复显示/g)).toHaveLength(1);
    expect(html).not.toContain('data-codex-transcript-surface="true"');
    expect(html).not.toContain('data-codex-transcript-cell-kind="assistant_markdown"');
  });

  it("keeps the final answer visible when same-turn process packets carry tool-only native transcript cells", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool",
        role: "assistant",
        content: "",
        timestamp: "2026-07-07T11:00:00Z",
        metadata: { turnId: "turn-native-answer" },
        toolCalls: [{ name: "grep_search_tool", status: "done", summary: "未找到匹配项" }],
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool",
          cells: [
            {
              id: "native-tool-only",
              kind: "tool_call",
              messageId: "assistant-native-tool",
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
      },
      {
        id: "assistant-native-answer",
        role: "assistant",
        content: "最终回答应该显示。",
        timestamp: "2026-07-07T11:00:10Z",
        metadata: { turnId: "turn-native-answer" },
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-answer",
          cells: [
            {
              id: "native-answer-visible",
              kind: "assistant_markdown",
              messageId: "assistant-native-answer",
              status: "completed",
              tone: "neutral",
              text: "最终回答应该显示。",
            },
          ],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
    ]);

    expect(html).toContain("grep_search_tool");
    expect(html).toContain("最终回答应该显示。");
    expect(html).toContain('data-codex-transcript-cell-kind="assistant_markdown"');
  });

  it("renders expandable native tool execution details instead of only the short summary", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool-detail",
        role: "assistant",
        content: "工具检查完成。",
        timestamp: "2026-07-07T11:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool-detail",
          cells: [
            {
              id: "native-tool-detail-cell",
              kind: "tool_call",
              messageId: "assistant-native-tool-detail",
              status: "completed",
              tone: "neutral",
              title: "code_symbol_tool",
              summary: '{\n"status": "ok",',
              operationIds: ["operation-code-symbol"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "tool_call:operation-code-symbol",
                    rawOperationId: "operation-code-symbol",
                    status: "completed",
                    title: "code_symbol_tool",
                    summary: '{\n"status": "ok",',
                    rawToolName: "code_symbol_tool",
                    runtimeKind: "tool",
                    resultPreview: "完整工具结果：命中 20 个符号",
                  },
                ],
                terminalOperations: [],
                terminalSessions: [],
                modelObservations: [],
              },
            },
            {
              id: "native-tool-detail-answer",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-detail",
              status: "completed",
              tone: "neutral",
              text: "工具检查完成。",
            },
          ],
          toolCalls: [
            {
              toolCallId: "tool_call:operation-code-symbol",
              rawOperationId: "operation-code-symbol",
              status: "completed",
              title: "code_symbol_tool",
              summary: '{\n"status": "ok",',
              rawToolName: "code_symbol_tool",
              runtimeKind: "tool",
              resultPreview: "完整工具结果：命中 20 个符号",
            },
          ],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      } as ConversationMessage,
    ]);

    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).toContain("code_symbol_tool");
    expect(html).toContain("完整工具结果：命中 20 个符号");
    expect(html).toContain("工具检查完成。");
  });

  it("renders native tool instructions and returned results without the tool summary", () => {
    const meaninglessSummary = '{"dirty_summary":"有 unstaged 改动，共 5 个变化文件"}';
    const html = renderConversation([
      {
        id: "assistant-native-tool-io",
        role: "assistant",
        content: "",
        timestamp: "2026-07-07T11:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool-io",
          cells: [
            {
              id: "native-tool-io-cell",
              kind: "tool_call",
              messageId: "assistant-native-tool-io",
              status: "completed",
              tone: "neutral",
              title: "cli_tool",
              summary: meaninglessSummary,
              operationIds: ["operation-cli"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "tool_call:operation-cli",
                    rawOperationId: "operation-cli",
                    terminalOperationId: "terminal-cli",
                    status: "completed",
                    title: "cli_tool",
                    summary: meaninglessSummary,
                    rawToolName: "cli_tool",
                    runtimeKind: "terminal",
                  },
                ],
                terminalOperations: [
                  {
                    operationId: "terminal-cli",
                    rawOperationId: "operation-cli",
                    toolCallId: "tool_call:operation-cli",
                    status: "completed",
                    title: "cli_tool",
                    request: {
                      displayCommand: "git status --short",
                      cwd: "C:/Users/17533/Desktop/Vibelution",
                    },
                    result: {
                      formattedOutput: "M web/src/components/conversation/ConversationView.tsx",
                      stdout: "M web/src/components/conversation/ConversationView.tsx",
                      stderr: "",
                      exitCode: 0,
                    },
                  },
                ],
                terminalSessions: [],
                modelObservations: [],
              },
            },
          ],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      } as ConversationMessage,
    ]);

    expect(html).toContain("cli_tool");
    expect(html).not.toContain('open=""');
    expect(html).toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).toContain('aria-label="展开或收起工具结果：cli_tool"');
    expect(html).toContain("git status --short");
    expect(html).toContain("M web/src/components/conversation/ConversationView.tsx");
    expect(html).not.toContain("指令与结果");
    expect(html).not.toContain(meaninglessSummary);
    expect(html).not.toContain("dirty_summary");
    expect(html).not.toContain("工作目录");
    expect(html).not.toContain("exitCode");
  });

  it("does not repeat the tool title as an instruction when no command was sent", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool-title-only",
        role: "assistant",
        content: "",
        timestamp: "2026-07-07T11:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool-title-only",
          cells: [
            {
              id: "native-tool-title-only-cell",
              kind: "tool_call",
              messageId: "assistant-native-tool-title-only",
              status: "completed",
              tone: "neutral",
              title: "glob_tool",
              summary: "glob_tool",
              operationIds: ["operation-glob"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "tool_call:operation-glob",
                    rawOperationId: "operation-glob",
                    status: "completed",
                    title: "glob_tool",
                    summary: "glob_tool",
                    rawToolName: "glob_tool",
                    runtimeKind: "tool",
                    resultPreview: "web/src/components/conversation/ConversationView.tsx",
                  },
                ],
                terminalOperations: [],
                terminalSessions: [],
                modelObservations: [],
              },
            },
          ],
          toolCalls: [],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      } as ConversationMessage,
    ]);

    expect(html).toContain("glob_tool");
    expect(html).toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).not.toContain("指令与结果");
    expect(html).toContain("web/src/components/conversation/ConversationView.tsx");
    expect(html).not.toContain(">指令</dt>");
  });

  it("keeps legacy process visible without rendering it as a Codex transcript when native transcript is unavailable", () => {
    const html = renderConversation([
      {
        id: "assistant-legacy",
        role: "assistant",
        content: "legacy response remains visible",
        timestamp: "2026-07-07T11:05:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "legacy_tool",
            summary: "legacy process renders",
          },
        ],
        timelineItems: [
          {
            id: "legacy-operation",
            kind: "operation",
            status: "completed",
            title: "legacy_tool",
            summary: "legacy process renders",
            operationIds: ["assistant-legacy-feedback-1"],
          },
        ],
      },
    ]);

    expect(html).toContain("legacy process renders");
    expect(html).toContain("data-agent-process-kind");
    expect(html).not.toContain('data-codex-transcript-surface="true"');
    expect(html).toContain('data-codex-transcript-surface-mode="empty"');
    expect(html).toContain('data-codex-transcript-projection-gap-reason="native_missing"');
  });
});
