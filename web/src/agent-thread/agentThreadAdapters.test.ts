import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import type { ConversationMessage } from "../api/types";
import {
  activeTurnLayerToConversationMessage,
  mergeAssistantDeltaIntoActiveTurnLayer,
} from "../routes/chatActiveTurnLayer";
import { conversationMessageToAgentMessage } from ".";

const adapterSource = readFileSync(new URL("./adapters.ts", import.meta.url), "utf8");
const typesSource = readFileSync(new URL("./types.ts", import.meta.url), "utf8");

describe("agent thread adapters", () => {
  it("does not export the retired batch ConversationMessage to AgentThread adapter", () => {
    expect(adapterSource).not.toContain("conversationMessagesToAgentThread");
    expect(adapterSource).not.toContain("ConversationMessagesToAgentThreadOptions");
  });

  it("declares AgentMessageRole without deriving it from the conversation DTO", () => {
    expect(typesSource).toContain('export type AgentMessageRole = "user" | "assistant";');
    expect(typesSource).not.toContain('ConversationMessage["role"]');
    expect(typesSource).not.toContain("ConversationMessage,");
  });

  it("keeps AgentThread model types independent from API DTO imports", () => {
    expect(typesSource).not.toContain("../api/types");
    expect(typesSource).not.toContain("ConversationFeedbackEvent");
    expect(typesSource).not.toContain("ConversationAttachment");
    expect(typesSource).not.toContain("SessionReferenceAttachment");
    expect(typesSource).not.toContain("MentalStateSnapshot");
    expect(typesSource).not.toContain("original?:");
  });

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
  });});
