import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";
import conversationViewSource from "./ConversationView.tsx?raw";
import toolActivityStyles from "./ConversationToolActivity.styles";
import styles from "./ConversationView.styles";

function renderConversation(
  messages: ConversationMessage[],
  processDisplayMode: "answer" | "trace" = "trace",
  companionMode = false,
  overrides: Partial<React.ComponentProps<typeof ConversationView>> = {},
) {
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
        companionMode={companionMode}
        assistantDisplayName="洛天依"
        assistantAvatarImageUrl="/avatars/luotianyi.png"
        assistantAvatarFallback="洛"
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
        {...overrides}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView native Codex transcript surface", () => {
  it("collapses an in-flight companion turn to one 微信式 typing status", () => {
    const html = renderConversation([
      {
        id: "assistant-companion-thinking",
        role: "assistant",
        timestamp: "2026-08-09T17:14:00Z",
        turnId: "turn-companion-thinking",
        status: "running",
        turnItems: [
          {
            id: "companion-reasoning-r1",
            itemId: "companion-reasoning",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-companion-thinking",
            type: "reasoning",
            status: "running",
            revision: 1,
            sequence: 1,
            terminal: false,
            text: "这段内部推理不能出现在虚拟人的聊天里。",
          },
          {
            id: "companion-tool-r1",
            itemId: "companion-tool",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-companion-thinking",
            type: "tool_call",
            callId: "call-companion",
            toolName: "private_tool",
            status: "running",
            revision: 1,
            sequence: 2,
            terminal: false,
          },
        ],
      },
    ], "trace", true);

    expect(html).toContain('data-companion-typing-status="true"');
    expect(html).toContain("正在输入…");
    expect(html.match(/正在输入…/g)).toHaveLength(1);
    expect(html).not.toContain('data-agent-message-id="assistant-companion-thinking"');
    expect(html).not.toContain("这段内部推理不能出现在虚拟人的聊天里");
    expect(html).not.toContain("private_tool");
    expect(html).not.toContain("状态");
    expect(html).not.toContain("思考中");
    expect(html).not.toContain("处理中");
  });

  it("aligns the companion typing status with the assistant message body rail", () => {
    const html = renderConversation([{
      id: "assistant-companion-typing-alignment",
      role: "assistant",
      timestamp: "2026-08-09T17:14:00Z",
      turnId: "turn-companion-typing-alignment",
      status: "running",
      turnItems: [{
        id: "companion-typing-alignment-r1",
        itemId: "companion-typing-alignment",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-companion-typing-alignment",
        type: "reasoning",
        status: "running",
        revision: 1,
        sequence: 1,
        terminal: false,
        text: "这段内部推理仍然隐藏。",
      }],
    }], "trace", true);

    expect(html).toContain('data-companion-typing-rail="assistant"');
    expect(html).toContain('src="/avatars/luotianyi.png"');
    expect(html).toContain('data-companion-typing-avatar="true"');
    expect(html).toContain(styles.companionTypingTurn);
    expect(html).toContain(styles.companionTypingContent);
    expect(styles.companionTypingTurn).toContain("max-w-[830px]");
    expect(styles.companionTypingTurn).toContain("justify-self-center");
    expect(styles.companionTypingTurn).toContain("grid-cols-[2rem_minmax(0,1fr)]");
    expect(styles.companionTypingContent).toContain("col-start-2");
  });

  it("removes the companion typing status as soon as a final answer starts streaming", () => {
    const html = renderConversation([
      {
        id: "assistant-companion-answering",
        role: "assistant",
        timestamp: "2026-08-09T17:14:00Z",
        turnId: "turn-companion-answering",
        status: "running",
        turnItems: [{
          id: "companion-answer-r1",
          itemId: "companion-answer",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-companion-answering",
          type: "agent_message",
          phase: "final_answer",
          status: "running",
          revision: 1,
          sequence: 1,
          terminal: false,
          text: "我已经开始回复你了。",
        }],
      },
    ], "trace", true);

    expect(html).toContain("我已经开始回复你了。");
    expect(html).not.toContain('data-companion-typing-status="true"');
    expect(html).not.toContain('data-codex-transcript-cell-kind="reasoning_summary"');
  });

  it("keeps terminal companion errors visible without leaving a typing status", () => {
    const html = renderConversation([
      {
        id: "assistant-companion-error",
        role: "assistant",
        timestamp: "2026-08-09T17:14:00Z",
        turnId: "turn-companion-error",
        status: "failed",
        turnItems: [{
          id: "companion-error-r1",
          itemId: "companion-error",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-companion-error",
          type: "error",
          code: "provider_error",
          status: "failed",
          revision: 1,
          sequence: 1,
          terminal: true,
          text: "这次没有连上模型。",
        }],
      },
    ], "trace", true);

    expect(html).toContain("这次没有连上模型。");
    expect(html).not.toContain('data-companion-typing-status="true"');
  });

  it("leaves the native process transcript unchanged for ordinary Agent sessions", () => {
    const html = renderConversation([
      {
        id: "assistant-agent-thinking",
        role: "assistant",
        timestamp: "2026-08-09T17:14:00Z",
        turnId: "turn-agent-thinking",
        status: "running",
        turnItems: [{
          id: "agent-reasoning-r1",
          itemId: "agent-reasoning",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-agent-thinking",
          type: "reasoning",
          status: "running",
          revision: 1,
          sequence: 1,
          terminal: false,
          text: "普通 Agent 的原生思考轨迹仍然可见。",
        }],
      },
    ]);

    expect(html).toContain("普通 Agent 的原生思考轨迹仍然可见。");
    expect(html).not.toContain('data-companion-typing-status="true"');
    expect(html).not.toContain('data-companion-typing-rail="assistant"');
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

  it("keeps completed thought cells terminal while the overall turn is still streaming", () => {
    const html = renderConversation([
      {
        id: "assistant-thought-lifecycle",
        role: "assistant",
        timestamp: "2026-08-09T17:14:00Z",
        turnId: "turn-thought-lifecycle",
        status: "running",
        turnItems: [
          {
            id: "thought-completed-r1",
            itemId: "thought-completed",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-thought-lifecycle",
            type: "agent_message",
            phase: "commentary",
            status: "completed",
            revision: 1,
            sequence: 1,
            terminal: true,
            text: "已经完成的历史思考。",
          },
          {
            id: "thought-running-r1",
            itemId: "thought-running",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-thought-lifecycle",
            type: "reasoning",
            status: "running",
            revision: 1,
            sequence: 2,
            terminal: false,
            text: "当前仍在进行的思考。",
          },
        ],
      },
    ]);

    const completedText = html.indexOf("已经完成的历史思考。");
    const runningText = html.indexOf("当前仍在进行的思考。");
    const completedStart = html.lastIndexOf("<section", completedText);
    const completedEnd = html.indexOf("</section>", completedText);
    const runningStart = html.lastIndexOf("<section", runningText);
    const runningEnd = html.indexOf("</section>", runningText);
    expect(completedText).toBeGreaterThan(-1);
    expect(runningText).toBeGreaterThan(-1);
    expect(completedStart).toBeGreaterThan(-1);
    expect(completedEnd).toBeGreaterThan(completedStart);
    expect(runningStart).toBeGreaterThan(-1);
    expect(runningEnd).toBeGreaterThan(runningStart);
    expect(html.slice(completedStart, completedEnd)).not.toContain(styles.statusSpinner);
    expect(html.slice(runningStart, runningEnd)).toContain(styles.statusSpinner);
  });

  it("does not derive individual thought streaming from the whole assistant turn", () => {
    expect(conversationViewSource).not.toContain(
      'input.status === "running" || input.status === "pending" || assistantTurnIsStreaming(message)',
    );
    expect(conversationViewSource).not.toContain(
      'item.status === "running" || item.status === "pending" || assistantTurnIsStreaming(message)',
    );
  });

  it("labels commentary as progress while keeping reasoning labeled as thinking", () => {
    const html = renderConversation([
      {
        id: "assistant-commentary-reasoning-labels",
        role: "assistant",
        timestamp: "2026-08-13T18:00:00Z",
        turnId: "turn-commentary-reasoning-labels",
        status: "completed",
        turnItems: [
          {
            id: "reasoning-label:0",
            itemId: "reasoning-label",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-commentary-reasoning-labels",
            type: "reasoning",
            status: "completed",
            revision: 0,
            sequence: 1,
            terminal: true,
            text: "这是模型推理摘要。",
          },
          {
            id: "commentary-label:0",
            itemId: "commentary-label",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-commentary-reasoning-labels",
            type: "agent_message",
            phase: "commentary",
            status: "completed",
            revision: 0,
            sequence: 2,
            terminal: true,
            text: "这是对用户可见的进展说明。",
          },
        ],
      },
    ]);

    const reasoningText = html.indexOf("这是模型推理摘要。");
    const commentaryText = html.indexOf("这是对用户可见的进展说明。");
    const reasoningStart = html.lastIndexOf("<section", reasoningText);
    const commentaryStart = html.lastIndexOf("<section", commentaryText);
    const reasoningEnd = html.indexOf("</section>", reasoningText);
    const commentaryEnd = html.indexOf("</section>", commentaryText);
    expect(html.slice(reasoningStart, reasoningEnd)).toContain("思考");
    expect(html.slice(commentaryStart, commentaryEnd)).toContain("进展");
    expect(html.slice(commentaryStart, commentaryEnd)).not.toContain("思考");
  });

  it("renders commentary in a clamped progress lane and drops the copy the answer repeats", () => {
    const repeated = "我已经定位到问题并完成修复，接下来运行定向测试验证没有回归。";
    const html = renderConversation([
      {
        id: "assistant-progress-lane",
        role: "assistant",
        timestamp: "2026-09-11T06:00:00Z",
        turnId: "turn-progress-lane",
        status: "completed",
        turnItems: [
          {
            id: "reasoning-lane:0",
            itemId: "reasoning-lane",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-progress-lane",
            type: "reasoning",
            status: "completed",
            revision: 0,
            sequence: 1,
            terminal: true,
            text: "这是内部推理，不占进展位置。",
          },
          {
            id: "progress-lane:0",
            itemId: "progress-lane",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-progress-lane",
            type: "agent_message",
            phase: "commentary",
            status: "completed",
            revision: 0,
            sequence: 2,
            terminal: true,
            text: "先检查配置，再运行回归测试。",
          },
          {
            id: "progress-dup:0",
            itemId: "progress-dup",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-progress-lane",
            type: "agent_message",
            phase: "commentary",
            status: "completed",
            revision: 0,
            sequence: 3,
            terminal: true,
            text: repeated,
          },
          {
            id: "answer-progress:0",
            itemId: "answer-progress",
            version: 3,
            sessionId: "session-1",
            turnId: "turn-progress-lane",
            type: "agent_message",
            phase: "final_answer",
            status: "completed",
            revision: 0,
            sequence: 4,
            terminal: true,
            text: repeated,
          },
        ],
      },
    ]);

    expect(html).toContain('data-codex-progress-cell="true"');
    expect(html).toContain("先检查配置，再运行回归测试。");
    expect(html).toContain('data-codex-progress-clamped="true"');
    expect(html).toContain("line-clamp-3");
    // The progress copy that repeats the final answer must paint once.
    expect(html.split(repeated).length - 1).toBe(1);
    expect(html).toContain("思考");
  });

  it("renders context compression outcomes in their canonical event order", () => {
    const marker = (
      turnId: string,
      code: string,
      title: string,
      text: string,
      status: "completed" | "failed",
    ): ConversationMessage => ({
      id: `${turnId}-message`,
      role: "assistant",
      timestamp: "2026-08-13T18:00:00Z",
      turnId,
      status,
      turnItems: [{
        id: `${turnId}-marker:0`,
        itemId: `${turnId}-marker`,
        version: 3,
        sessionId: "session-1",
        turnId,
        type: "status",
        code,
        title,
        text,
        status,
        revision: 0,
        sequence: 1,
        terminal: true,
        diagnosticSummary: { kind: "context_compression_marker", status: code },
      }],
    });
    const html = renderConversation([
      marker("turn-applied", "context_compression_applied", "上下文已压缩", "节省 5,800 tokens", "completed"),
      marker("turn-skipped", "context_compression_skipped_low_savings", "压缩未应用 · 收益不足", "保留原上下文", "completed"),
      marker("turn-failed", "context_compression_failed_preserved", "压缩失败 · 已保留原上下文", "RuntimeError", "failed"),
    ]);

    const applied = html.indexOf("上下文已压缩");
    const skipped = html.indexOf("压缩未应用 · 收益不足");
    const failed = html.indexOf("压缩失败 · 已保留原上下文");
    expect(applied).toBeGreaterThan(-1);
    expect(skipped).toBeGreaterThan(applied);
    expect(failed).toBeGreaterThan(skipped);
    expect(html).not.toContain("context_compression_applied");
    expect(html).not.toContain("context_compression_skipped_low_savings");
    expect(html).not.toContain("context_compression_failed_preserved");
  });

  it("collapses a settled reasoning cell to a preview and unmounts its body", () => {
    const reasoning = (status: "running" | "completed"): ConversationMessage => ({
      id: `assistant-reasoning-${status}`,
      role: "assistant",
      timestamp: "2026-09-11T05:00:00Z",
      turnId: `turn-reasoning-${status}`,
      status,
      turnItems: [{
        id: `reasoning-${status}-r1`,
        itemId: `reasoning-${status}`,
        version: 3,
        sessionId: "session-1",
        turnId: `turn-reasoning-${status}`,
        type: "reasoning",
        status,
        revision: 1,
        sequence: 1,
        terminal: status === "completed",
        text: "先确认这个函数的两条来源路径，再看函数体。",
      }],
    });

    const live = renderConversation([reasoning("running")]);
    expect(live).toContain('data-thought-expanded="true"');
    expect(live).toContain('data-thought-scroll-body="true"');
    expect(live).toContain("先确认这个函数的两条来源路径");

    const settled = renderConversation([reasoning("completed")]);
    expect(settled).toContain('data-thought-expanded="false"');
    // Collapsed means the long body is not mounted at all: the finished thought
    // stops re-rendering its text on every transcript update.
    expect(settled).not.toContain('data-thought-scroll-body="true"');
    // The one-line preview keeps the collapsed cell scannable.
    expect(settled).toContain(styles.timelineThoughtInlinePreview);
  });

  it("labels a retry row in human copy instead of the model_retry protocol code", () => {
    const html = renderConversation([
      {
        id: "assistant-retry-row",
        role: "assistant",
        timestamp: "2026-09-11T07:00:00Z",
        turnId: "turn-retry-row",
        status: "completed",
        turnItems: [{
          id: "retry-row-r1",
          itemId: "retry-row",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-retry-row",
          type: "retry",
          attempt: 1,
          targetItemId: "answer",
          reason: "模型连接正在重试...\n第 1/3 次；原因：server_error。本轮仍在继续，请不要重复提交。",
          status: "completed",
          revision: 1,
          sequence: 1,
          terminal: true,
        }],
      },
    ]);

    expect(html).toContain('data-codex-transcript-cell-kind="status"');
    expect(html).toContain("请求重试");
    expect(html).not.toContain(">model_retry<");
  });

  it("offers a copy action on a settled assistant answer", () => {
    const answer = (status: "running" | "completed"): ConversationMessage => ({
      id: `assistant-copy-${status}`,
      role: "assistant",
      timestamp: "2026-09-11T08:00:00Z",
      turnId: `turn-copy-${status}`,
      status,
      turnItems: [{
        id: `answer-copy-${status}:0`,
        itemId: `answer-copy-${status}`,
        version: 3,
        sessionId: "session-1",
        turnId: `turn-copy-${status}`,
        type: "agent_message",
        phase: "final_answer",
        status,
        revision: 0,
        sequence: 1,
        terminal: status === "completed",
        text: "这是可以复制的最终回答。",
      }],
    });

    const settled = renderConversation([answer("completed")]);
    expect(settled).toContain("这是可以复制的最终回答。");
    // Static render has no loaded dictionary pack, so t() falls back to the key.
    expect(settled).toContain('aria-label="copyAnswer"');

    // While the answer is still streaming the clipboard must stay untouched.
    const streaming = renderConversation([answer("running")]);
    expect(streaming).not.toContain('aria-label="copyAnswer"');
  });

  it("offers regenerate only for the latest settled assistant answer", () => {
    const answer = (status: "running" | "completed"): ConversationMessage => ({
      id: `assistant-copy-${status}`,
      role: "assistant",
      timestamp: "2026-09-11T08:10:00Z",
      turnId: `turn-copy-${status}`,
      status,
      turnItems: [{
        id: `answer-copy-${status}:0`,
        itemId: `answer-copy-${status}`,
        version: 3,
        sessionId: "session-1",
        turnId: `turn-copy-${status}`,
        type: "agent_message",
        phase: "final_answer",
        status,
        revision: 0,
        sequence: 1,
        terminal: status === "completed",
        text: "可以重新生成的回答。",
      }],
    });
    const onRegenerateAssistantMessage = () => undefined;

    const settled = renderConversation(
      [answer("completed")],
      "trace",
      false,
      {
        regenerableAssistantMessageId: "assistant-copy-completed",
        onRegenerateAssistantMessage,
      },
    );
    expect(settled).toContain('aria-label="regenerateAnswer"');

    const historical = renderConversation(
      [answer("completed")],
      "trace",
      false,
      {
        regenerableAssistantMessageId: "assistant-another-turn",
        onRegenerateAssistantMessage,
      },
    );
    expect(historical).not.toContain('aria-label="regenerateAnswer"');

    const streaming = renderConversation(
      [answer("running")],
      "trace",
      false,
      {
        regenerableAssistantMessageId: "assistant-copy-running",
        onRegenerateAssistantMessage,
      },
    );
    expect(streaming).not.toContain('aria-label="regenerateAnswer"');
  });

  it("shows what a running tool is working on, from its arguments", () => {
    const runningTool = (
      toolName: string,
      input: string,
      status: "running" | "completed" = "running",
    ): ConversationMessage => ({
      id: `assistant-${toolName}-${status}`,
      role: "assistant",
      timestamp: "2026-09-11T06:00:00Z",
      turnId: `turn-${toolName}-${status}`,
      status,
      turnItems: [{
        id: `${toolName}-${status}-r1`,
        itemId: `${toolName}-${status}`,
        version: 3,
        sessionId: "session-1",
        turnId: `turn-${toolName}-${status}`,
        type: "tool_call",
        callId: `call-${toolName}-${status}`,
        toolName,
        status,
        revision: 1,
        sequence: 1,
        terminal: status === "completed",
        input,
      }],
    });

    // While it runs there is no result to summarize, so the subject has to come
    // from the arguments; otherwise the row says only "读取文件" with no target.
    const readRunning = renderConversation([
      runningTool("read_file_tool", JSON.stringify({ path: "web/src/routes/chat/useSessionDetailStream.ts" })),
    ], "trace");
    expect(readRunning).toContain('data-codex-tool-subject="true"');
    expect(readRunning).toContain("useSessionDetailStream.ts");

    const searchRunning = renderConversation([
      runningTool("grep_search_tool", JSON.stringify({ pattern: "resolveSessionDetail" })),
    ], "trace");
    expect(searchRunning).toContain("resolveSessionDetail");
  });

  it("renders the apply_patch payload as an inline diff", () => {
    const patchMessage: ConversationMessage = {
      id: "assistant-apply-patch",
      role: "assistant",
      timestamp: "2026-09-11T06:00:00Z",
      turnId: "turn-apply-patch",
      status: "completed",
      turnItems: [{
        id: "apply-patch-r1",
        itemId: "apply-patch",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-apply-patch",
        type: "tool_call",
        callId: "call-apply-patch",
        toolName: "apply_patch_tool",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        input: JSON.stringify({
          patch_text: [
            "*** Begin Patch",
            "*** Update File: web/src/app.ts",
            "@@",
            "-const value = 1;",
            "+const value = 2;",
            "*** End Patch",
          ].join("\n"),
        }),
      }],
    };

    const html = renderConversation([patchMessage], "trace");
    expect(html).toContain('data-codex-patch-diff="true"');
    expect(html).toContain("web/src/app.ts");
    expect(html).toContain('data-patch-line-kind="del"');
    expect(html).toContain('data-patch-line-kind="add"');
    expect(html).toContain("const value = 1;");
    expect(html).toContain("const value = 2;");
  });

  it("suppresses the standalone turn error banner when the same turn rendered a final answer", () => {
    const answeredMessage: ConversationMessage = {
      id: "assistant-answered",
      role: "assistant",
      timestamp: "2026-05-22T00:01:00Z",
      turnId: "turn-1",
      status: "completed",
      turnItems: [{
        id: "answer-r1",
        itemId: "answer-1",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "agent_message",
        phase: "final_answer",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        text: "结论：无需修改。",
      }],
    };
    const turnError = {
      message: "模型服务上游暂时失败，本轮没有完成。",
      errorType: "provider_upstream_error",
      reasonCode: "upstream_unavailable",
      turnId: "turn-1",
    };

    const supersededHtml = renderConversation([answeredMessage], "trace", false, { turnError });
    expect(supersededHtml).toContain("无需修改。");
    expect(supersededHtml).not.toContain("turnErrorText");

    const unmatchedHtml = renderConversation([answeredMessage], "trace", false, {
      turnError: { ...turnError, turnId: "turn-other" },
    });
    expect(unmatchedHtml).toContain("turnErrorText");
  });

  it("offers the failed-turn card one retry action and no per-attempt retry trail", () => {
    const turnError = {
      message: "模型服务上游暂时失败，本轮没有完成。",
      errorType: "provider_upstream_error",
      reasonSummary: "provider 上游服务不可用",
      recoverable: true,
      timestamp: "2026-09-13T01:00:00Z",
      turnId: "turn-retry",
      retryHistory: [
        { attempt: 1, maxAttempts: 3, category: "server_error" },
        { attempt: 3, maxAttempts: 3, category: "server_error" },
      ],
    } as React.ComponentProps<typeof ConversationView>["turnError"];
    const userMessage = {
      id: "user-retry",
      role: "user",
      timestamp: "2026-09-13T01:00:00Z",
      turnId: "turn-retry",
      status: "completed",
      content: "请修复登录失败的问题。",
    } as ConversationMessage;

    const html = renderConversation([userMessage], "trace", false, {
      turnError,
      onRetryTurn: () => undefined,
    });
    expect(html).toContain("已重试 3 次");
    expect(html).toContain('aria-label="重试这一轮"');
    expect(html).not.toContain("第 1/3 次");

    const withoutHandler = renderConversation([userMessage], "trace", false, { turnError });
    expect(withoutHandler).not.toContain('aria-label="重试这一轮"');
  });

  it("renders a plan tool call as an inline step checklist", () => {
    const planMessage: ConversationMessage = {
      id: "assistant-plan",
      role: "assistant",
      timestamp: "2026-05-22T00:02:00Z",
      turnId: "turn-plan",
      status: "running",
      turnItems: [{
        id: "plan-call-r1",
        itemId: "plan-call",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-plan",
        type: "tool_call",
        callId: "call-plan",
        toolName: "plan_update_tool",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        input: JSON.stringify({
          plan: [
            { step: "审查工具契约", status: "completed" },
            { step: "补齐回归测试", status: "in_progress" },
            { step: "运行完整验证", status: "pending" },
          ],
          explanation: "同步当前对齐进度",
        }),
      }],
    };

    const html = renderConversation([planMessage], "trace");
    expect(html).toContain('data-codex-tool-checklist="true"');
    expect(html).toContain('data-codex-tool-checklist-tool="plan_update_tool"');
    expect(html.match(/data-checklist-item-status="completed"/g)).toHaveLength(1);
    expect(html.match(/data-checklist-item-status="in_progress"/g)).toHaveLength(1);
    expect(html.match(/data-checklist-item-status="pending"/g)).toHaveLength(1);
    expect(html).toContain("审查工具契约");
    expect(html).toContain("补齐回归测试");
    expect(html).toContain("运行完整验证");
    expect(html).toContain("同步当前对齐进度");
    expect(html).not.toContain('data-codex-tool-activity-item="true"');
  });

  it("renders a task creation tool call as a pending task checklist", () => {
    const taskMessage: ConversationMessage = {
      id: "assistant-task",
      role: "assistant",
      timestamp: "2026-05-22T00:03:00Z",
      turnId: "turn-task",
      status: "running",
      turnItems: [{
        id: "task-call-r1",
        itemId: "task-call",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-task",
        type: "tool_call",
        callId: "call-task",
        toolName: "task_create_tool",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        input: JSON.stringify({
          task_list: [
            { description: "复现缺陷" },
            { description: "修复持久化判定" },
          ],
          goal: "修复错误卡常驻",
        }),
      }],
    };

    const html = renderConversation([taskMessage], "trace");
    expect(html).toContain('data-codex-tool-checklist="true"');
    expect(html).toContain('data-codex-tool-checklist-tool="task_create_tool"');
    expect(html.match(/data-checklist-item-status="pending"/g)).toHaveLength(2);
    expect(html).toContain("复现缺陷");
    expect(html).toContain("修复持久化判定");
    expect(html).toContain("修复错误卡常驻");
    expect(html).not.toContain('data-codex-tool-activity-item="true"');
  });
});
