import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

function renderConversation(messages: ConversationMessage[]) {
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
        processDisplayMode="trace"
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
    expect(html).toContain('open=""');
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
