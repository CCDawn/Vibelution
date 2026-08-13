import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";
import conversationViewSource from "./ConversationView.tsx?raw";
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
});
