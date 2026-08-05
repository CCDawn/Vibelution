import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  chronologicalConversationMessages,
  messageSequenceOrder,
} from "./conversationMessageOrder";

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T21:44:00Z",
    ...overrides,
  };
}

describe("conversationMessageOrder", () => {
  it("reads sequence from metadata and trailing message ids", () => {
    expect(messageSequenceOrder(message({ metadata: { messageIndex: 3 } }))).toBe(3);
    expect(messageSequenceOrder(message({ metadata: { seq: 7 } }))).toBe(7);
    expect(messageSequenceOrder(message({ id: "session-abc-message-12" }))).toBe(12);
  });

  it("orders by journal sequence even when wall-clock timestamps are reversed", () => {
    const ordered = chronologicalConversationMessages([
      message({
        id: "session-1-message-2",
        role: "assistant",
        content: "answer",
        // Wrong/older wall clock — must not win over message index.
        timestamp: "2026-08-05T09:00:00Z",
      }),
      message({
        id: "session-1-message-1",
        role: "user",
        content: "question",
        timestamp: "2026-08-05T10:00:00Z",
      }),
    ]);
    expect(ordered.map((item) => item.id)).toEqual([
      "session-1-message-1",
      "session-1-message-2",
    ]);
  });

  it("falls back to timestamp order when no journal sequence is available", () => {
    const ordered = chronologicalConversationMessages([
      message({
        id: "assistant-new",
        content: "new answer",
        timestamp: "2026-07-09T01:27:00Z",
      }),
      message({
        id: "user-new",
        content: "new question",
        timestamp: "2026-07-09T01:26:58Z",
      }),
      message({
        id: "assistant-old",
        content: "old answer",
        timestamp: "2026-07-09T01:26:48Z",
      }),
      message({
        id: "user-old",
        content: "old question",
        timestamp: "2026-07-09T01:26:16Z",
      }),
    ]);
    expect(ordered.map((item) => item.id)).toEqual([
      "user-old",
      "assistant-old",
      "user-new",
      "assistant-new",
    ]);
  });

  it("prefers messageIndex metadata over reversed timestamps", () => {
    const ordered = chronologicalConversationMessages([
      message({
        id: "a",
        role: "assistant",
        timestamp: "2026-08-05T08:00:00Z",
        metadata: { messageIndex: 2 },
      }),
      message({
        id: "u",
        role: "user",
        timestamp: "2026-08-05T09:00:00Z",
        metadata: { messageIndex: 1 },
      }),
    ]);
    expect(ordered.map((item) => item.id)).toEqual(["u", "a"]);
  });
});
