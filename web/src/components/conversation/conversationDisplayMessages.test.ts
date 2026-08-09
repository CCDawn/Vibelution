import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";

const displayMessagesModulePath = new URL("./conversationDisplayMessages.ts", import.meta.url);
const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

async function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  if (!existsSync(displayMessagesModulePath)) {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
  }
  const module = await import("./conversationDisplayMessages");
  return module.projectConversationDisplayMessages(messages);
}

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T21:44:00Z",
    ...overrides,
  };
}

describe("conversation display message projection", () => {
  it("keeps ConversationView from owning display message DTO merge rules", () => {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
    expect(conversationViewSource).toContain("projectConversationDisplayMessages");
    expect(conversationViewSource).not.toContain("function mergeAdjacentTurnErrorMessages");
    expect(conversationViewSource).not.toContain("const mergedMessages: ConversationMessage[]");
  });
  it("normalizes display messages to chronological order before rendering", async () => {
    const projected = await projectConversationDisplayMessages([
      message({
        id: "assistant-new",
        role: "assistant",
        content: "new answer",
        timestamp: "2026-07-09T01:27:00Z",
      }),
      message({
        id: "user-new",
        role: "user",
        content: "new question",
        timestamp: "2026-07-09T01:26:58Z",
      }),
      message({
        id: "assistant-old",
        role: "assistant",
        content: "old answer",
        timestamp: "2026-07-09T01:26:48Z",
      }),
      message({
        id: "user-old",
        role: "user",
        content: "old question",
        timestamp: "2026-07-09T01:26:16Z",
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual([
      "user-old",
      "assistant-old",
      "user-new",
      "assistant-new",
    ]);
  });});
