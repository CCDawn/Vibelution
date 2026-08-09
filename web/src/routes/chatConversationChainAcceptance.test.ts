import { describe, expect, it } from "vitest";

import type { SessionStreamEvent, SessionTurnItem } from "../api/types";
import fixture from "../../../tests/fixtures/conversation_chain/canonical_tool_followup_v2.json";
import {
  activeTurnLayerToConversationMessage,
  mergeAssistantDeltaIntoActiveTurnLayer,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";

type AssistantDelta = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

describe("shared canonical conversation-chain acceptance", () => {
  it("keeps repeated user text distinct through canonical turn identity", () => {
    const [first, second] = fixture.turns;

    expect(first.user_text).toBe("继续");
    expect(second.user_text).toBe("继续");
    expect(first.turn_id).not.toBe(second.turn_id);
    expect(first.invocation_id).not.toBe(second.invocation_id);
    expect(first.submission_id).not.toBe(second.submission_id);
    expect(first.session_id).toBe(second.session_id);
  });});
