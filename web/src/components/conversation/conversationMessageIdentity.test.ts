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
  });});
