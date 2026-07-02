import { describe, expect, it } from "vitest";

import type { AgentMessage } from ".";
import { agentMessageToSections } from ".";

describe("agent message sections", () => {
  it("groups process parts, content parts, and context parts without flattening tool calls", () => {
    const message: AgentMessage = {
      id: "assistant-1",
      role: "assistant",
      createdAt: "2026-07-02T09:00:00Z",
      streaming: true,
      turnId: "turn-1",
      source: { kind: "conversation-message", id: "assistant-1" },
      parts: [
        {
          id: "assistant-1-thought",
          type: "thought",
          text: "先检查结构",
          status: "done",
        },
        {
          id: "assistant-1-status",
          type: "runtime-event",
          kind: "status",
          name: "model_request",
          status: "running",
          summary: "正在请求模型",
        },
        {
          id: "assistant-1-tool",
          type: "tool-call",
          name: "read_file_tool",
          status: "done",
          summary: "读取 agent-thread",
          arguments: { path: "web/src/agent-thread" },
          resultPreview: "export type AgentMessage",
        },
        {
          id: "assistant-1-text",
          type: "text",
          channel: "answer",
          text: "已经完成 section 归组",
        },
        {
          id: "assistant-1-reference",
          type: "reference",
          reference: {
            kind: "session",
            sessionId: "session-ref",
            title: "历史会话",
          },
        },
      ],
    };

    const sections = agentMessageToSections(message);

    expect(sections.map((section) => section.kind)).toEqual(["process", "content", "context"]);
    expect(sections[0]).toMatchObject({
      id: "assistant-1-section-process-0",
      kind: "process",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual([
      "thought",
      "runtime-event",
      "tool-call",
    ]);
    expect(sections[0].parts[2]).toMatchObject({
      type: "tool-call",
      name: "read_file_tool",
      arguments: { path: "web/src/agent-thread" },
      resultPreview: "export type AgentMessage",
    });
    expect(sections[1].parts.map((part) => part.id)).toEqual(["assistant-1-text"]);
    expect(sections[2].parts.map((part) => part.type)).toEqual(["reference"]);
  });

  it("keeps user content and user context in separate render sections", () => {
    const message: AgentMessage = {
      id: "user-1",
      role: "user",
      createdAt: "2026-07-02T09:01:00Z",
      streaming: false,
      source: { kind: "conversation-message", id: "user-1" },
      parts: [
        {
          id: "user-1-text",
          type: "text",
          channel: "user",
          text: "请参考截图",
        },
        {
          id: "user-1-attachment",
          type: "attachment",
          attachment: {
            artifactId: "artifact-1",
            filename: "screen.png",
            url: "/artifacts/screen.png",
            contentType: "image/png",
            kind: "image",
            status: "ready",
          },
        },
      ],
    };

    const sections = agentMessageToSections(message);

    expect(sections.map((section) => section.kind)).toEqual(["content", "context"]);
    expect(sections[0].parts.map((part) => part.id)).toEqual(["user-1-text"]);
    expect(sections[1].parts.map((part) => part.id)).toEqual(["user-1-attachment"]);
  });
});
