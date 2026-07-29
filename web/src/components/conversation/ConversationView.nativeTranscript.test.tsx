import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";
import toolActivityStyles from "./ConversationToolActivity.styles";
import styles from "./ConversationView.styles";

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
    expect(html).toContain('data-codex-process-disclosure="true"');
    expect(html).toContain('data-codex-process-state="failed"');
    expect(html).not.toContain('open=""');
    expect(html).not.toContain("responseSection");
  });

  it("folds tool cells recorded after the final answer into the process disclosure", () => {
    const html = renderConversation([
      {
        id: "message-final-before-tool",
        role: "assistant",
        content: "这是最终回答。",
        timestamp: "2026-07-13T00:00:00.000Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-final-before-tool",
          cells: [
            {
              id: "final-before-tool-answer",
              kind: "assistant_markdown",
              messageId: "message-final-before-tool",
              status: "completed",
              tone: "neutral",
              text: "这是最终回答。",
            },
            {
              id: "tool-recorded-after-final",
              kind: "tool_call",
              messageId: "message-final-before-tool",
              status: "completed",
              tone: "neutral",
              title: "code_symbol_tool",
              summary: "后置工具结果",
              operationIds: ["operation-after-final"],
            },
          ],
        },
      },
    ]);

    const processStart = html.indexOf('data-codex-process-disclosure="true"');
    const processOpenEnd = html.indexOf(">", processStart);
    const finalStart = html.indexOf('data-codex-final-response="true"');

    expect(processStart).toBeGreaterThanOrEqual(0);
    expect(html.slice(processStart, finalStart)).toContain("后置工具结果");
    expect(finalStart).toBeGreaterThan(html.indexOf("后置工具结果"));
    expect(html.slice(processStart, processOpenEnd)).not.toContain('open=""');
  });

  it("folds a native terminal continuation into its command across assistant messages", () => {
    const terminalId = "terminal:sandbox-cross-message";
    const html = renderConversation([
      {
        id: "user-terminal-command",
        role: "user",
        content: "Run the acceptance command.",
        timestamp: "2026-07-27T20:02:00.000Z",
      },
      {
        id: "assistant-terminal-command",
        role: "assistant",
        content: "",
        timestamp: "2026-07-27T20:02:01.000Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-terminal-command",
          cells: [
            {
              id: "assistant-terminal-command-cell",
              kind: "tool_call",
              messageId: "assistant-terminal-command",
              status: "running",
              tone: "running",
              title: "exec_command",
              operationIds: ["exec-operation"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "call-exec",
                    rawOperationId: "exec-operation",
                    status: "running",
                    title: "exec_command",
                    rawToolName: "exec_command",
                    runtimeKind: "terminal",
                    terminalOperationId: "terminal-operation-exec",
                  },
                ],
                terminalOperations: [
                  {
                    operationId: "terminal-operation-exec",
                    rawOperationId: "exec-operation",
                    toolCallId: "call-exec",
                    terminalId,
                    kind: "ExecCommand",
                    status: "running",
                    request: { displayCommand: "ping -n 3 127.0.0.1", cwd: "" },
                  },
                ],
                terminalSessions: [
                  {
                    terminalId,
                    createdByOperationId: "terminal-operation-exec",
                    operationIds: ["terminal-operation-exec"],
                    status: "running",
                  },
                ],
                modelObservations: [],
              },
            },
          ],
        },
      },
      {
        id: "assistant-terminal-write",
        role: "assistant",
        content: "",
        timestamp: "2026-07-27T20:02:04.000Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-terminal-write",
          cells: [
            {
              id: "assistant-terminal-write-cell",
              kind: "tool_call",
              messageId: "assistant-terminal-write",
              status: "completed",
              tone: "warning",
              title: "write_stdin",
              summary: "[WARNING | Exit Code: 7] command finished",
              operationIds: ["write-operation"],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "call-write",
                    rawOperationId: "write-operation",
                    status: "completed",
                    title: "write_stdin",
                    rawToolName: "write_stdin",
                    runtimeKind: "terminal",
                    terminalOperationId: "terminal-operation-write",
                  },
                ],
                terminalOperations: [
                  {
                    operationId: "terminal-operation-write",
                    rawOperationId: "write-operation",
                    toolCallId: "call-write",
                    terminalId,
                    kind: "WriteStdin",
                    status: "completed",
                    request: { displayCommand: "", cwd: "" },
                    result: { exitCode: 7, formattedOutput: "[WARNING | Exit Code: 7] command finished" },
                  },
                ],
                terminalSessions: [
                  {
                    terminalId,
                    createdByOperationId: "terminal-operation-exec",
                    operationIds: ["terminal-operation-exec", "terminal-operation-write"],
                    status: "completed",
                  },
                ],
                modelObservations: [],
              },
            },
          ],
        },
      },
    ]);

    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(1);
    expect(html).toContain('data-codex-transcript-cell-tone="warning"');
    expect(html).not.toContain('data-conversation-part-key="assistant-terminal-write-cell"');
  });

  it("aligns expanded compact tool diagnostics with the tool body column", () => {
    const html = renderConversation([
      {
        id: "message-compact-tool-error",
        role: "assistant",
        content: "",
        timestamp: "2026-07-27T10:17:00.000Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "message-compact-tool-error",
          cells: [
            {
              id: "compact-tool-error",
              kind: "error_notice",
              messageId: "message-compact-tool-error",
              status: "failed",
              tone: "error",
              title: "write_stdin",
              text: "终端会话已结束",
              operationIds: ["operation-write-stdin"],
              diagnosticSummary: {
                reasonCode: "terminal_stdin_unavailable",
                reasonSummary: "终端会话已结束，不能继续写入。",
              },
            },
          ],
        },
      },
    ]);

    const diagnosticAttribute = html.indexOf('data-codex-error-diagnostic="true"');
    const detailsStart = html.lastIndexOf("<details", diagnosticAttribute);
    const detailsEnd = html.indexOf("</details>", detailsStart);
    const detailsMarkup = html.slice(detailsStart, detailsEnd);
    const summaryEnd = detailsMarkup.indexOf("</summary>");

    expect(diagnosticAttribute).toBeGreaterThanOrEqual(0);
    expect(detailsStart).toBeGreaterThanOrEqual(0);
    expect(detailsEnd).toBeGreaterThan(detailsStart);
    expect(detailsMarkup.slice(0, summaryEnd)).toContain("写入终端");
    expect(detailsMarkup.slice(0, summaryEnd)).not.toContain("itemChevron");
    expect(detailsMarkup.slice(0, summaryEnd)).not.toContain("技术详情");
    expect(detailsMarkup.indexOf("turnErrorReasonList")).toBeGreaterThan(summaryEnd);
    expect(toolActivityStyles.itemDetailsBody).not.toContain("ml-");
    expect(toolActivityStyles.itemDetailsBody).not.toContain("mr-");
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
    const toolIndex = html.indexOf("读取");
    const finalIndex = html.indexOf("检查完成。");
    expect(commentaryIndex).toBeGreaterThan(-1);
    expect(toolIndex).toBeGreaterThan(commentaryIndex);
    expect(finalIndex).toBeGreaterThan(toolIndex);
    expect(html).toContain('data-codex-tool-detail="true"');
    expect(html).toContain('data-codex-process-disclosure="true"');
    expect(html).toContain("已处理");
    expect(html).not.toContain("个阶段");
    expect(html).not.toContain('open=""');
    expect(html).toContain('data-codex-final-response="true"');
    expect(html).toContain('data-codex-transcript-cell-channel="commentary"');
    expect(html).toContain('data-codex-transcript-cell-phase="tool_call"');
    expect(html).toContain("file loaded");
    expect(html).toContain("完成");
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
    expect(html).toContain("native process renders");
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

    expect(html).toContain(">搜索<");
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
                terminalOperations: [
                  {
                    operationId: "terminal-code-symbol",
                    rawOperationId: "operation-code-symbol",
                    toolCallId: "tool_call:operation-code-symbol",
                    terminalId: "terminal-code-symbol",
                    kind: "ExecCommand",
                    status: "completed",
                    request: {
                      displayCommand: "inspect symbols",
                      cwd: "C:/Users/17533/Desktop/Vibelution",
                    },
                    durationSeconds: 2.9,
                  },
                ],
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
    expect(html).toContain(">代码图谱<");
    expect(html).toContain("完整工具结果：命中 20 个符号");
    expect(html).not.toContain("完成 2.9s");
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

    expect(html).toContain(">命令<");
    expect(html).toContain('data-codex-process-disclosure="true"');
    expect(html).not.toContain('open=""');
    expect(html).not.toContain('data-codex-tool-detail-toggle="inline-symbol"');
    expect(html).toContain('aria-label="展开或收起工具结果：命令"');
    expect(html).toContain('data-codex-terminal-detail="true"');
    expect(html).toContain(">Shell<");
    expect(html).toContain("$ git status --short");
    expect(html).toContain("M web/src/components/conversation/ConversationView.tsx");
    expect(html).not.toContain("指令与结果");
    expect(html).not.toContain(meaninglessSummary);
    expect(html).not.toContain("dirty_summary");
    expect(html).not.toContain("工作目录");
    expect(html).not.toContain("exitCode");
  });

  it("keeps commentary primary and renders adjacent tools inline before the final answer", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool-activity",
        role: "assistant",
        content: "",
        timestamp: "2026-07-18T01:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool-activity",
          cells: [
            {
              id: "commentary-before-tools",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-activity",
              status: "completed",
              tone: "neutral",
              phase: "commentary",
              text: "先检查当前实现。",
            },
            ...[1, 2, 3].map((index) => ({
              id: `code-tool-${index}`,
              kind: "tool_call" as const,
              messageId: "assistant-native-tool-activity",
              status: "completed" as const,
              tone: "neutral" as const,
              title: "code_symbol_tool",
              summary: index === 3 ? "定位 ConversationLogger" : '{"status":"ok",',
            })),
            {
              id: "commentary-after-tools",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-activity",
              status: "completed",
              tone: "neutral",
              phase: "commentary",
              text: "已定位关键调用。",
            },
            {
              id: "final-after-tools",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-activity",
              status: "completed",
              tone: "neutral",
              phase: "final",
              text: "最终回答保持在最后。",
            },
          ],
        },
      } as ConversationMessage,
    ]);

    const before = html.indexOf("先检查当前实现。");
    const disclosure = html.indexOf('data-codex-process-disclosure="true"');
    const toolActivity = html.indexOf('data-codex-tool-activity="items"');
    const after = html.indexOf("已定位关键调用。");
    const final = html.indexOf("最终回答保持在最后。");
    expect(html).not.toContain("运行了 3 个工具");
    expect(html).toContain("代码图谱");
    expect(html).toContain(">· 3 次</span>");
    expect(html.match(/data-codex-tool-activity-item="true"/g)).toHaveLength(3);
    expect(html).not.toContain('data-codex-tool-activity-group="true"');
    expect(html).not.toContain("3 次调用");
    expect(html).not.toContain('{&quot;status&quot;:&quot;ok&quot;,');
    expect(before).toBeGreaterThan(-1);
    expect(disclosure).toBeGreaterThan(-1);
    expect(before).toBeGreaterThan(disclosure);
    expect(toolActivity).toBeGreaterThan(before);
    expect(after).toBeGreaterThan(toolActivity);
    expect(final).toBeGreaterThan(after);
    expect(html).toContain('data-codex-final-response="true"');
  });

  it("keeps a long same-tool batch between its surrounding commentary cells", () => {
    const html = renderConversation([
      {
        id: "assistant-native-tool-batch",
        role: "assistant",
        content: "",
        timestamp: "2026-07-18T01:00:00Z",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-tool-batch",
          cells: [
            {
              id: "commentary-before-batch",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-batch",
              status: "completed",
              tone: "neutral",
              phase: "commentary",
              text: "Inspecting the current implementation.",
            },
            ...Array.from({ length: 4 }, (_, index) => ({
              id: `code-tool-batch-${index + 1}`,
              kind: "tool_call" as const,
              messageId: "assistant-native-tool-batch",
              status: "completed" as const,
              tone: "neutral" as const,
              title: "code_symbol_tool",
              summary: "ok",
            })),
            {
              id: "commentary-after-batch",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-batch",
              status: "completed",
              tone: "neutral",
              phase: "commentary",
              text: "The relevant calls are located.",
            },
            {
              id: "final-after-batch",
              kind: "assistant_markdown",
              messageId: "assistant-native-tool-batch",
              status: "completed",
              tone: "neutral",
              phase: "final",
              text: "Final answer remains last.",
            },
          ],
        },
      } as ConversationMessage,
    ]);

    const before = html.indexOf("Inspecting the current implementation.");
    const batch = html.indexOf('data-codex-tool-activity-batch="true"');
    const after = html.indexOf("The relevant calls are located.");
    const final = html.indexOf("Final answer remains last.");
    expect(before).toBeGreaterThan(-1);
    expect(html).toContain('data-codex-tool-activity="items"');
    expect(batch).toBeGreaterThan(before);
    expect(after).toBeGreaterThan(batch);
    expect(final).toBeGreaterThan(after);
    expect(html).toContain('data-codex-tool-activity-count="4"');
    expect(html).toContain('data-codex-final-response="true"');
  });

  it("keeps a running native tool summary on the main row and nests lifecycle trace in details", () => {
    const html = renderConversation([
      {
        id: "assistant-native-running-cli",
        role: "assistant",
        content: "",
        timestamp: "2026-07-14T08:10:00Z",
        streaming: true,
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "assistant-native-running-cli",
          cells: [
            {
              id: "native-running-cli-cell",
              kind: "tool_call",
              messageId: "assistant-native-running-cli",
              status: "running",
              tone: "neutral",
              title: "cli_tool",
              summary: "正在检查工作区",
              operationIds: ["operation-running-cli"],
              rolloutTraceEvents: [
                {
                  id: "tool-call-started",
                  kind: "ToolCallStarted",
                  status: "completed",
                  toolCallId: "tool_call:operation-running-cli",
                },
                {
                  id: "runtime-started",
                  kind: "RuntimeStarted",
                  status: "running",
                  toolCallId: "tool_call:operation-running-cli",
                  terminalOperationId: "terminal-running-cli",
                },
              ],
              toolLifecycleModel: {
                toolCalls: [
                  {
                    toolCallId: "tool_call:operation-running-cli",
                    rawOperationId: "operation-running-cli",
                    terminalOperationId: "terminal-running-cli",
                    status: "running",
                    title: "cli_tool",
                    summary: "正在检查工作区",
                    rawToolName: "cli_tool",
                    runtimeKind: "terminal",
                    resultPreview: "PowerShell 命令仍在运行",
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

    const detailsStart = html.indexOf('data-codex-tool-detail="true"');
    const detailsEnd = html.indexOf("</details>", detailsStart);
    const technicalAttribute = html.indexOf('data-codex-tool-technical-details="true"');
    const technicalDetailsStart = html.lastIndexOf("<details", technicalAttribute);
    const technicalOpenTag = html.slice(
      technicalDetailsStart,
      html.indexOf(">", technicalDetailsStart) + 1,
    );
    const traceStart = html.indexOf('aria-label="工具生命周期"');
    expect(html).toContain(">命令<");
    expect(html).toContain("处理中");
    expect(html).not.toContain(">运行中<");
    expect(html).toContain("正在检查工作区");
    expect(detailsStart).toBeGreaterThan(-1);
    expect(traceStart).toBeGreaterThan(detailsStart);
    expect(traceStart).toBeLessThan(detailsEnd);
    expect(technicalDetailsStart).toBeGreaterThan(detailsStart);
    expect(technicalOpenTag).not.toContain('open=""');
    expect(html).toContain("技术详情");
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

    expect(html).toContain(">列出文件<");
    expect(html).not.toContain('data-codex-tool-detail-toggle="inline-symbol"');
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
