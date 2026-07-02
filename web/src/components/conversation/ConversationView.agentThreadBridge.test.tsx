import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

function renderConversation(messages: ConversationMessage[], activeTurnMessage?: ConversationMessage) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-agent-thread"
        title="Session"
        phase="running"
        messages={messages}
        activeTurnMessage={activeTurnMessage}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView agent thread bridge", () => {
  it("projects legacy conversation props into an AgentThread without changing visible output", () => {
    const html = renderConversation(
      [
        {
          id: "user-1",
          role: "user",
          content: "继续前端重构",
          timestamp: "2026-07-02T09:00:00Z",
        },
      ],
      {
        id: "assistant-active",
        role: "assistant",
        content: "正在接入统一消息模型",
        timestamp: "2026-07-02T09:00:01Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "running",
            name: "read_file_tool",
            summary: "读取 ConversationView",
          },
        ],
        metadata: {
          kind: "session_active_turn_layer",
          turnId: "turn-1",
        },
      },
    );

    expect(html).toContain('data-agent-thread-id="session-agent-thread"');
    expect(html).toContain('data-agent-thread-source-kind="conversation-view"');
    expect(html).toContain('data-agent-thread-status="streaming"');
    expect(html).toContain('data-agent-thread-message-count="2"');
    expect(html).toContain("继续前端重构");
    expect(html).toContain("正在接入统一消息模型");
  });

  it("keeps active thought visible when feedback status events are the only process events", () => {
    const html = renderConversation(
      [],
      {
        id: "assistant-active-thought",
        role: "assistant",
        content: "正在形成回答",
        thought: "推理片段来自 thought 字段",
        timestamp: "2026-07-02T09:12:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_request",
            summary: "正在请求模型",
          },
        ],
        metadata: {
          kind: "session_active_turn_layer",
          turnId: "turn-2",
        },
      },
    );

    expect(html).toContain("推理片段来自 thought 字段");
    expect(html).toContain("正在形成回答");
  });
});
