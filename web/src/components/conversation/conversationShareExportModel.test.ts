import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import {
  buildConversationShareExportTurns,
  SHARE_EXPORT_ASSISTANT_PREVIEW_MAX_CHARS,
} from "./conversationShareExportModel";

function assistantItem(turnId: string, text: string, sequence = 1): SessionTurnItem {
  return {
    id: `${turnId}-item-${sequence}`,
    itemId: `${turnId}-item-${sequence}`,
    version: 3,
    sessionId: "sess-1",
    turnId,
    status: "completed",
    revision: 0,
    sequence,
    type: "agent_message",
    phase: "final_answer",
    text,
  } as SessionTurnItem;
}

const MESSAGES: ConversationMessage[] = [
  { id: "s-message-1", role: "user", content: "第一问 **加粗**", timestamp: "2026-01-02T10:30:00" },
  {
    id: "s-message-2",
    role: "assistant",
    turnId: "turn-1",
    status: "completed",
    timestamp: "2026-01-02T10:30:05",
    turnItems: [assistantItem("turn-1", "第一答")],
  },
  { id: "s-message-3", role: "user", content: "第二问", timestamp: "2026-01-02T10:31:00" },
  {
    id: "s-message-4",
    role: "assistant",
    turnId: "turn-2",
    status: "completed",
    timestamp: "2026-01-02T10:31:10",
    turnItems: [assistantItem("turn-2", "第二答")],
  },
];

describe("conversationShareExportModel", () => {
  it("groups messages into turns and adopts the assistant turnId", () => {
    const turns = buildConversationShareExportTurns(MESSAGES);

    expect(turns.map((turn) => turn.turnId)).toEqual(["turn-1", "turn-2"]);
    expect(turns.map((turn) => turn.turnNumber)).toEqual([1, 2]);
    expect(turns[0].userPreviewText).toBe("第一问 **加粗**");
    expect(turns[0].assistantPreviewText).toBe("第一答");
    expect(turns[0].timestamp).toBe("2026-01-02T10:30:00");
  });

  it("opens assistant-anchored turns and keeps user-only turns selectable", () => {
    const turns = buildConversationShareExportTurns([
      MESSAGES[1],
      MESSAGES[2],
    ] as ConversationMessage[]);

    expect(turns).toHaveLength(2);
    expect(turns[0].turnId).toBe("turn-1");
    expect(turns[0].userPreviewText).toBe("");
    expect(turns[1].turnId).toBe("s-message-3");
    expect(turns[1].assistantPreviewText).toBe("");
    expect(turns[1].timestamp).toBe("2026-01-02T10:31:00");
  });

  it("flags attachment-bearing turns and clamps long previews", () => {
    const longAnswer = "很长的回答".repeat(120);
    const turns = buildConversationShareExportTurns([
      {
        id: "s-message-1",
        role: "user",
        content: "看图",
        timestamp: "2026-01-02T10:30:00",
        attachments: [{
          artifactId: "a-1",
          filename: "shot.png",
          url: "/u",
          imageUrl: "/u",
          downloadUrl: "/u",
          contentType: "image/png",
          sizeBytes: 10,
          kind: "user_image",
          status: "ready",
        }],
      },
      {
        id: "s-message-2",
        role: "assistant",
        turnId: "turn-1",
        status: "completed",
        timestamp: "2026-01-02T10:30:05",
        turnItems: [assistantItem("turn-1", longAnswer)],
      },
    ] as ConversationMessage[]);

    expect(turns[0].hasAttachments).toBe(true);
    expect(turns[0].assistantPreviewText.length).toBeLessThanOrEqual(
      SHARE_EXPORT_ASSISTANT_PREVIEW_MAX_CHARS,
    );
  });

  it("collapses whitespace in previews and returns no turns for an empty transcript", () => {
    expect(buildConversationShareExportTurns([])).toEqual([]);
    const turns = buildConversationShareExportTurns([
      { id: "s-message-1", role: "user", content: "多行\n\n  预览", timestamp: "t" },
    ] as ConversationMessage[]);
    expect(turns[0].userPreviewText).toBe("多行 预览");
  });
});
