import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { AgentMessage, AgentThread } from "../../agent-thread";
import { useAgentThread } from "./useAgentThread";

const hookSource = readFileSync(new URL("./useAgentThread.ts", import.meta.url), "utf8");
const retiredHookPath = new URL("./useAgentThreadProjection.ts", import.meta.url);

function assistantMessage(patch: Partial<AgentMessage> = {}): AgentMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    createdAt: "2026-07-03T10:55:00Z",
    streaming: true,
    turnId: "turn-agent-thread",
    source: { kind: "conversation-message", id: "assistant-1" },
    parts: [
      {
        id: "assistant-1-tool",
        type: "tool-call",
        status: "running",
        name: "read_file_tool",
        summary: "读取 ConversationView",
      },
      { id: "assistant-1-text", type: "text", channel: "answer", text: "正在收束对话链路" },
    ],
    ...patch,
  };
}

function userMessage(): AgentMessage {
  return {
    id: "user-1",
    role: "user",
    createdAt: "2026-07-03T10:54:00Z",
    streaming: false,
    source: { kind: "conversation-message", id: "user-1" },
    parts: [{ id: "user-1-text", type: "text", channel: "user", text: "继续拆 ConversationView" }],
  };
}

function HookProbe({
  sessionId,
  agentMessages,
  onThread,
}: {
  sessionId: string;
  agentMessages: AgentMessage[];
  onThread: (thread: AgentThread) => void;
}) {
  const thread = useAgentThread(sessionId, agentMessages);
  onThread(thread);
  return <div data-thread-status={thread.status}>{thread.messages.length}</div>;
}

describe("useAgentThread", () => {
  it("builds a conversation-view AgentThread from AgentMessage projections without reading ConversationMessage DTOs", () => {
    expect(hookSource).toContain("export function useAgentThread");
    expect(hookSource).not.toContain("../../api/types");
    expect(hookSource).not.toContain("ConversationMessage");
    expect(hookSource).not.toContain("conversationMessageToAgentMessage");
    expect(existsSync(retiredHookPath)).toBe(false);

    let projectedThread: AgentThread | undefined;

    const html = renderToStaticMarkup(
      <HookProbe
        sessionId="session-thread-projection"
        agentMessages={[userMessage(), assistantMessage()]}
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
