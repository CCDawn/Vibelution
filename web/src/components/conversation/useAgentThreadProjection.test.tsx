import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { AgentThread } from "../../agent-thread";
import { useAgentThreadProjection } from "./useAgentThreadProjection";

function assistantMessage(patch: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "正在收束对话链路",
    timestamp: "2026-07-03T10:55:00Z",
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
      turnId: "turn-agent-thread",
    },
    ...patch,
  };
}

function HookProbe({
  sessionId,
  messages,
  onThread,
}: {
  sessionId: string;
  messages: ConversationMessage[];
  onThread: (thread: AgentThread) => void;
}) {
  const thread = useAgentThreadProjection(sessionId, messages);
  onThread(thread);
  return <div data-thread-status={thread.status}>{thread.messages.length}</div>;
}

describe("useAgentThreadProjection", () => {
  it("projects conversation timeline messages into a conversation-view AgentThread", () => {
    let projectedThread: AgentThread | undefined;

    const html = renderToStaticMarkup(
      <HookProbe
        sessionId="session-thread-projection"
        messages={[
          {
            id: "user-1",
            role: "user",
            content: "继续拆 ConversationView",
            timestamp: "2026-07-03T10:54:00Z",
          },
          assistantMessage(),
        ]}
        onThread={(thread) => {
          projectedThread = thread;
        }}
      />,
    );

    expect(html).toContain('data-thread-status="streaming"');
    expect(projectedThread).toMatchObject({
      id: "session-thread-projection",
      source: { kind: "conversation-view", id: "session-thread-projection" },
      status: "streaming",
    });
    expect(projectedThread?.messages.map((message) => message.id)).toEqual(["user-1", "assistant-1"]);
    expect(projectedThread?.messages[1].turnId).toBe("turn-agent-thread");
    expect(projectedThread?.messages[1].parts.map((part) => part.type)).toEqual(["tool-call", "text"]);
  });
});
