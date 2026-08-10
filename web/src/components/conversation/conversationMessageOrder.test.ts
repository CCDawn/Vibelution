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

  it("keeps input order for unsequenced messages despite reversed timestamps", () => {
    // Optimistic user messages carry the client clock while live assistant
    // layers carry the server clock; wall-clock must not reorder them.
    const ordered = chronologicalConversationMessages([
      message({
        id: "user-optimistic",
        role: "user",
        content: "new question",
        timestamp: "2026-07-09T01:27:00Z",
      }),
      message({
        id: "assistant-new",
        role: "assistant",
        content: "new answer",
        timestamp: "2026-07-09T01:26:58Z",
      }),
      message({
        id: "user-old",
        role: "user",
        content: "old question",
        timestamp: "2026-07-09T01:26:48Z",
      }),
      message({
        id: "assistant-old",
        role: "assistant",
        content: "old answer",
        timestamp: "2026-07-09T01:26:16Z",
      }),
    ]);
    expect(ordered.map((item) => item.id)).toEqual([
      "user-optimistic",
      "assistant-new",
      "user-old",
      "assistant-old",
    ]);
  });

  it("keeps optimistic user message before active assistant layer under server clock skew", () => {
    // Regression: assistant_delta carries the server timestamp (older than the
    // client clock when the turn started), which previously moved the assistant
    // layer above the optimistic user message and made the timeline look
    // reversed until a later delta refreshed the timestamp. Input order mirrors
    // the real render path: canonical timeline (with the optimistic user
    // message appended last) followed by the active turn layer.
    const ordered = chronologicalConversationMessages([
      message({
        id: "optimistic-user-submission-abc",
        role: "user",
        content: "question",
        timestamp: "2026-08-10T10:00:05Z",
        metadata: {
          optimisticUserMessage: true,
          clientSubmissionId: "submission-abc",
          pending: true,
        },
      }),
      message({
        id: "session-1-message-active-turn-1",
        role: "assistant",
        content: "answer",
        timestamp: "2026-08-10T10:00:00Z",
        turnItems: [],
        metadata: { kind: "session_active_turn_layer" },
      }),
    ]);

    expect(ordered.map((item) => item.id)).toEqual([
      "optimistic-user-submission-abc",
      "session-1-message-active-turn-1",
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

  it("keeps a shared optimistic submission in user then assistant order despite clock skew", () => {
    const ordered = chronologicalConversationMessages([
      message({
        id: "assistant-active",
        role: "assistant",
        timestamp: "2026-08-10T00:00:00Z",
        metadata: { clientSubmissionId: "submission-live" },
      }),
      message({
        id: "user-optimistic",
        role: "user",
        timestamp: "2026-08-10T00:00:02Z",
        metadata: { clientSubmissionId: "submission-live" },
      }),
    ]);

    expect(ordered.map((item) => item.id)).toEqual(["user-optimistic", "assistant-active"]);
  });
});
