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

describe("ConversationView native Codex transcript surface", () => {it("does not render internal pipeline text when native transcripts carry it as assistant markdown", () => {
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
  });});
