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

  it("exposes AgentMessage section metadata on conversation turns", () => {
    const html = renderConversation([
      {
        id: "assistant-sections",
        role: "assistant",
        content: "最终回答",
        timestamp: "2026-07-02T09:20:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "read_file_tool",
            summary: "读取 ConversationView",
          },
        ],
        references: [
          {
            kind: "session",
            sessionId: "session-ref",
            title: "历史会话",
          },
        ],
      },
    ]);

    expect(html).toContain('data-agent-message-id="assistant-sections"');
    expect(html).toContain('data-agent-section-kinds="process content context"');
    expect(html).toContain('data-agent-section-count="3"');
  });

  it("renders conversation context from AgentMessage context sections", () => {
    const html = renderConversation([
      {
        id: "user-context",
        role: "user",
        content: "继续看这个上下文",
        timestamp: "2026-07-02T09:30:00Z",
        attachments: [
          {
            artifactId: "context-image.png",
            filename: "context.png",
            url: "/api/sessions/session-agent-thread/artifacts/context-image.png",
            imageUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png",
            downloadUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png?download=1",
            contentType: "image/png",
            sizeBytes: 128,
            kind: "user_image",
            status: "ready",
          },
        ],
        references: [
          {
            kind: "session",
            referenceId: "session:context-ref",
            sessionId: "context-ref",
            title: "旧会话摘录",
            agentDisplayName: "前端代理",
          },
        ],
      },
    ]);

    expect(html).toContain('data-agent-message-id="user-context"');
    expect(html).toContain('data-agent-section-kinds="content context"');
    expect(html).toContain('data-agent-context-section-id="user-context-section-context-1"');
    expect(html).toContain('data-agent-context-part-count="2"');
    expect(html).toContain('data-agent-context-part-type="attachment"');
    expect(html).toContain('data-agent-context-part-type="reference"');
    expect(html).toContain('src="/api/sessions/session-agent-thread/artifacts/context-image.png"');
    expect(html).toContain("context.png");
    expect(html).toContain("旧会话摘录");
    expect(html).toContain("前端代理");
  });

  it("renders user and assistant text from AgentMessage content sections", () => {
    const html = renderConversation([
      {
        id: "user-content",
        role: "user",
        content: "用户正文来自 content section",
        timestamp: "2026-07-02T09:40:00Z",
      },
      {
        id: "assistant-content",
        role: "assistant",
        content: "助手回答来自 content section",
        timestamp: "2026-07-02T09:40:03Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "read_file_tool",
            summary: "读取正文渲染",
          },
        ],
      },
    ]);

    expect(html).toContain('data-agent-message-id="user-content"');
    expect(html).toContain('data-agent-message-id="assistant-content"');
    expect(html).toContain('data-agent-content-section-ids="user-content-section-content-0"');
    expect(html).toContain('data-agent-content-section-ids="assistant-content-section-content-1"');
    expect(html).toContain('data-agent-content-channel="user"');
    expect(html).toContain('data-agent-content-channel="answer"');
    expect(html).toContain("用户正文来自 content section");
    expect(html).toContain("助手回答来自 content section");
  });

  it("renders assistant process controls from AgentMessage process sections", () => {
    const html = renderConversation([
      {
        id: "assistant-process",
        role: "assistant",
        content: "过程完成后的回答",
        timestamp: "2026-07-02T09:45:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "先确认 process section",
            resultPreview: "先确认 process section",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "read_file_tool",
            summary: "读取过程渲染",
          },
        ],
      },
    ]);

    expect(html).toContain('data-agent-message-id="assistant-process"');
    expect(html).toContain('data-agent-section-kinds="process content"');
    expect(html).toContain('data-agent-process-section-ids="assistant-process-section-process-0"');
    expect(html).toContain('data-agent-process-kind="answer-only"');
    expect(html).toContain("工具调用 1");
    expect(html).toContain("过程完成后的回答");
  });
});
