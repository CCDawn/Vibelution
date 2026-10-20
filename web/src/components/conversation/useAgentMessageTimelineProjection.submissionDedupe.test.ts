import { describe, expect, it } from "vitest";
import type { ConversationMessage } from "../../api/types";
import { dedupeSettledUserSubmissions } from "./useAgentMessageTimelineProjection";

function userMessage(
  id: string,
  metadata: Record<string, unknown>,
  content = "hi",
): ConversationMessage {
  return { id, role: "user", content, metadata } as unknown as ConversationMessage;
}

describe("dedupeSettledUserSubmissions", () => {
  it("keeps the committed user row when its optimistic twin shares the submission id", () => {
    const optimistic = userMessage("optimistic-user-sub-1", {
      clientSubmissionId: "sub-1",
      optimisticUserMessage: true,
    });
    const canonical = userMessage("session-1-message-9", { clientSubmissionId: "sub-1" });

    const rows = dedupeSettledUserSubmissions([optimistic, canonical]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("session-1-message-9");
  });

  it("does not depend on message order for the committed row to win", () => {
    const optimistic = userMessage("optimistic-user-sub-2", {
      clientSubmissionId: "sub-2",
      optimisticUserMessage: true,
    });
    const canonical = userMessage("session-1-message-10", { clientSubmissionId: "sub-2" });

    const rows = dedupeSettledUserSubmissions([canonical, optimistic]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("session-1-message-10");
  });

  it("keeps a lone optimistic row while the canonical row has not landed yet", () => {
    const optimistic = userMessage("optimistic-user-sub-3", {
      clientSubmissionId: "sub-3",
      optimisticUserMessage: true,
    });

    const rows = dedupeSettledUserSubmissions([optimistic]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("optimistic-user-sub-3");
  });

  it("leaves user rows without a submission identity untouched", () => {
    const first = userMessage("session-1-message-1", {});
    const second = userMessage("session-1-message-2", {});

    const rows = dedupeSettledUserSubmissions([first, second]);

    expect(rows.map((row) => row.id)).toEqual([
      "session-1-message-1",
      "session-1-message-2",
    ]);
  });

  it("never collapses assistant rows through the user submission identity", () => {
    const assistant = {
      id: "session-1-message-live-9",
      role: "assistant",
      content: "answer",
      metadata: { clientSubmissionId: "sub-4" },
    } as unknown as ConversationMessage;

    const rows = dedupeSettledUserSubmissions([assistant]);

expect(rows).toHaveLength(1);
  });

  it("keeps two identical prompts that carry different submission identities", () => {
    const first = userMessage("session-1-message-11", { clientSubmissionId: "sub-a" });
    const second = userMessage("session-1-message-12", { clientSubmissionId: "sub-b" });

    const rows = dedupeSettledUserSubmissions([first, second]);

    expect(rows.map((row) => row.id)).toEqual([
      "session-1-message-11",
      "session-1-message-12",
    ]);
  });

  it("keeps the first committed row when two committed rows share one submission identity", () => {
    const first = userMessage("session-1-message-13", { clientSubmissionId: "sub-c" });
    const second = userMessage("session-1-message-14", { clientSubmissionId: "sub-c" });

    const rows = dedupeSettledUserSubmissions([first, second]);

    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe("session-1-message-13");
  });
});