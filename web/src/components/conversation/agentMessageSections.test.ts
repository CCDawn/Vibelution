import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import {
  agentMessageContextSections,
  agentMessageContentSections,
  agentMessageProcessSections,
  buildAgentMessageSectionState,
} from "./agentMessageSections";
import agentMessageSectionsSource from "./agentMessageSections.ts?raw";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "msg",
    role: "user",
    content: "",
    timestamp: "2026-05-20T14:12:39",
    ...overrides,
  };
}

function sectionState(message: ConversationMessage) {
  return buildAgentMessageSectionState(conversationMessageToAgentMessage(message));
}

describe("agentMessageSections", () => {
  it("does not export retired ConversationMessage content or block helpers", () => {
    expect(agentMessageSectionsSource).not.toMatch(/export function (?:hasUserContent|has(?:Response|Thought|Mental|Tool)Block)\b/);
  });  it("selects AgentMessage context sections without flattening attachments or references", () => {
    const userMessage = message({
      id: "user-context",
      role: "user",
      content: "继续看这个上下文",
      attachments: [
        {
          artifactId: "context-image.png",
          filename: "context.png",
          imageUrl: "/api/sessions/session-1/artifacts/context-image.png",
          contentType: "image/png",
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
        },
      ],
    });

    const sections = agentMessageContextSections(conversationMessageToAgentMessage(userMessage));

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "user-context-section-context-1",
      kind: "context",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual(["attachment", "reference"]);
  });

  it("selects AgentMessage content sections without mixing in context parts", () => {
    const userMessage = message({
      id: "user-content",
      role: "user",
      content: "继续看这个正文",
      attachments: [
        {
          artifactId: "content-image.png",
          filename: "content.png",
          imageUrl: "/api/sessions/session-1/artifacts/content-image.png",
          contentType: "image/png",
          kind: "user_image",
          status: "ready",
        },
      ],
    });

    const sections = agentMessageContentSections(conversationMessageToAgentMessage(userMessage));

    expect(sections).toHaveLength(1);
    expect(sections[0]).toMatchObject({
      id: "user-content-section-content-0",
      kind: "content",
    });
    expect(sections[0].parts.map((part) => part.type)).toEqual(["text"]);
    expect(sections[0].parts.map((part) => part.channel)).toEqual(["user"]);
  });it("shows operator text as direct message content", () => {
    const userMessage = message({
      role: "user",
      content: "你知道你上文说了什么吗",
    });
    const state = sectionState(userMessage);

    expect(state.hasUserContent).toBe(true);
    expect(state.hasResponseBlock).toBe(false);
  });it("keeps assistant-only diagnostic sections scoped away from operator messages", () => {
    const userMessage = message({
      role: "user",
      content: "继续",
      thought: "hidden",
      mentalSnapshot: {
        mood: "open",
        feeling: "",
        whisper: "",
        summary: "",
        cognitiveState: "",
        confidence: 0,
        sampleSize: 0,
        interventionCount: 0,
        updatedAt: "",
        source: "",
      },
      toolCalls: [{ name: "rg", status: "completed" }],
    });

    const state = sectionState(userMessage);
    expect(state.hasThoughtBlock).toBe(false);
    expect(state.hasMentalBlock).toBe(false);
    expect(state.hasToolBlock).toBe(false);
  });

});
