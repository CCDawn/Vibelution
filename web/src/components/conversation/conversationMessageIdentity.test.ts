import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import {
  conversationMessageMetadataText,
  conversationMessageTurnId,
  projectedConversationMessageIds,
  projectedConversationMessageIdsOrSelf,
} from "./conversationMessageIdentity";

const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");
const timelineProcessProjectionSource = readFileSync(
  new URL("./timelineMessageProcessProjection.ts", import.meta.url),
  "utf8",
);
const agentTimelineProjectionSource = readFileSync(
  new URL("./useAgentMessageTimelineProjection.ts", import.meta.url),
  "utf8",
);

function message(patch: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "message-a",
    role: "assistant",
    content: "",
    timestamp: "2026-07-04T07:02:00Z",
    ...patch,
  };
}

describe("conversation message identity helpers", () => {
  it("normalizes metadata text and turn ids", () => {
    expect(conversationMessageMetadataText({ turnId: " live:turn-1 " }, "turnId")).toBe("live:turn-1");
    expect(conversationMessageMetadataText({ count: 3 }, "count")).toBe("3");
    expect(conversationMessageMetadataText({ ok: false }, "ok")).toBe("false");
    expect(conversationMessageMetadataText({ nested: { id: 1 } }, "nested")).toBe("");
    expect(conversationMessageTurnId(message({ metadata: { turnId: "live:turn-1" } }))).toBe("turn-1");
    expect(conversationMessageTurnId(message({ metadata: { turnId: "turn-2" } }))).toBe("turn-2");
  });

  it("normalizes projected message id metadata with or without self fallback", () => {
    const projected = message({
      id: "base",
      metadata: {
        projectedMessageIds: [" first ", "", 9, false],
      },
    });
    const plain = message({ id: "plain" });

    expect(projectedConversationMessageIds(projected)).toEqual(["first", "9", "false"]);
    expect(projectedConversationMessageIds(plain)).toEqual([]);
    expect(projectedConversationMessageIdsOrSelf(projected)).toEqual(["first", "9", "false"]);
    expect(projectedConversationMessageIdsOrSelf(plain)).toEqual(["plain"]);
  });

  it("keeps identity helpers out of render and projection modules", () => {
    expect(conversationViewSource).toContain("./conversationMessageIdentity");
    expect(conversationViewSource).not.toContain("function projectedConversationMessageIds");
    expect(conversationViewSource).not.toContain("function conversationMessageTurnId");
    expect(timelineProcessProjectionSource).toContain("./conversationMessageIdentity");
    expect(timelineProcessProjectionSource).not.toContain("function metadataText");
    expect(agentTimelineProjectionSource).toContain("./conversationMessageIdentity");
    expect(agentTimelineProjectionSource).not.toContain("function metadataText");
    expect(agentTimelineProjectionSource).not.toContain("function conversationMessageTurnId");
  });
});
