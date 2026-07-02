import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../api/types";
import { activeTurnLayerToAgentMessage, mergeAssistantDeltaIntoActiveTurnLayer } from "../routes/chatActiveTurnLayer";
import {
  conversationMessageToAgentMessage,
  conversationMessagesToAgentThread,
} from ".";

describe("agent thread adapters", () => {
  it("maps a user conversation message to text, attachment, and reference parts", () => {
    const message: ConversationMessage = {
      id: "user-1",
      role: "user",
      content: "请结合这张图和会话继续分析",
      timestamp: "2026-07-02T08:00:00Z",
      attachments: [
        {
          artifactId: "artifact-1",
          filename: "screen.png",
          url: "/artifacts/screen.png",
          imageUrl: "/artifacts/screen.png",
          downloadUrl: "/download/screen.png",
          contentType: "image/png",
          sizeBytes: 1024,
          kind: "image",
          status: "ready",
        },
      ],
      references: [
        {
          kind: "session",
          sessionId: "session-ref",
          title: "历史会话",
        },
      ],
    };

    const agentMessage = conversationMessageToAgentMessage(message);

    expect(agentMessage).toMatchObject({
      id: "user-1",
      role: "user",
      createdAt: "2026-07-02T08:00:00Z",
      streaming: false,
    });
    expect(agentMessage.parts.map((part) => part.type)).toEqual(["text", "attachment", "reference"]);
    expect(agentMessage.parts[0]).toMatchObject({
      id: "user-1-text",
      type: "text",
      channel: "user",
      text: "请结合这张图和会话继续分析",
    });
  });

  it("prefers ordered feedback event parts before assistant answer text", () => {
    const message: ConversationMessage = {
      id: "assistant-1",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-07-02T08:01:00Z",
      thought: "legacy thought should not duplicate",
      toolCalls: [
        {
          name: "legacy_tool",
          status: "done",
          summary: "legacy summary should not duplicate",
        },
      ],
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "先检查上下文",
          resultPreview: "先检查上下文",
        },
        {
          sequence: 2,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型",
        },
        {
          sequence: 3,
          kind: "tool",
          status: "done",
          name: "read_file_tool",
          summary: "读取 ConversationView",
          resultPreview: "export function ConversationView",
          relatedThoughtSequence: 1,
        },
      ],
      metadata: {
        turnId: "turn-1",
      },
    };

    const agentMessage = conversationMessageToAgentMessage(message);

    expect(agentMessage.turnId).toBe("turn-1");
    expect(agentMessage.parts.map((part) => part.type)).toEqual([
      "thought",
      "runtime-event",
      "tool-call",
      "text",
    ]);
    expect(agentMessage.parts[0]).toMatchObject({
      id: "assistant-1-feedback-1",
      type: "thought",
      status: "done",
      text: "先检查上下文",
      sequence: 1,
    });
    expect(agentMessage.parts[2]).toMatchObject({
      id: "assistant-1-feedback-3",
      type: "tool-call",
      name: "read_file_tool",
      status: "done",
      summary: "读取 ConversationView",
      resultPreview: "export function ConversationView",
      relatedThoughtSequence: 1,
    });
    expect(agentMessage.parts[3]).toMatchObject({
      id: "assistant-1-text",
      type: "text",
      channel: "answer",
      text: "最终回答",
    });
  });

  it("uses legacy thought and tool calls only when feedback events are absent", () => {
    const message: ConversationMessage = {
      id: "assistant-legacy",
      role: "assistant",
      content: "旧链路回答",
      timestamp: "2026-07-02T08:02:00Z",
      streaming: true,
      thought: "旧链路思考",
      toolCalls: [
        {
          name: "grep_search_tool",
          status: "running",
          summary: "搜索 adapter",
          arguments: { query: "adapter" },
        },
      ],
    };

    const agentMessage = conversationMessageToAgentMessage(message);

    expect(agentMessage.streaming).toBe(true);
    expect(agentMessage.parts.map((part) => part.type)).toEqual(["thought", "tool-call", "text"]);
    expect(agentMessage.parts[0]).toMatchObject({
      id: "assistant-legacy-thought",
      type: "thought",
      text: "旧链路思考",
      status: "running",
    });
    expect(agentMessage.parts[1]).toMatchObject({
      id: "assistant-legacy-tool-0",
      type: "tool-call",
      name: "grep_search_tool",
      status: "running",
      arguments: { query: "adapter" },
    });
  });

  it("wraps conversation messages into a stable agent thread", () => {
    const thread = conversationMessagesToAgentThread(
      "session-1",
      [
        {
          id: "user-1",
          role: "user",
          content: "你好",
          timestamp: "2026-07-02T08:00:00Z",
        },
        {
          id: "assistant-1",
          role: "assistant",
          content: "你好，我在",
          timestamp: "2026-07-02T08:00:01Z",
          streaming: true,
        },
      ],
      { source: { kind: "session", id: "session-1" } },
    );

    expect(thread).toMatchObject({
      id: "session-1",
      source: { kind: "session", id: "session-1" },
      status: "streaming",
    });
    expect(thread.messages.map((message) => message.id)).toEqual(["user-1", "assistant-1"]);
  });

  it("maps the active turn layer into the same agent message model", () => {
    const layer = mergeAssistantDeltaIntoActiveTurnLayer(undefined, {
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 7,
      stage: "model_request",
      content: "",
      thought: "",
      contentDelta: "正在形成回答",
      thoughtDelta: "推理片段",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型",
        },
      ],
      updatedAt: "2026-07-02T08:03:00Z",
      done: false,
    });

    const agentMessage = activeTurnLayerToAgentMessage(layer);

    expect(agentMessage?.id).toBe("session-1-message-active-turn-1");
    expect(agentMessage?.source.kind).toBe("conversation-message");
    expect(agentMessage?.turnId).toBe("turn-1");
    expect(agentMessage?.parts.map((part) => part.type)).toEqual(["runtime-event", "thought", "text"]);
    expect(agentMessage?.parts[0]).toMatchObject({
      type: "runtime-event",
      name: "model_request",
      status: "running",
    });
  });
});
