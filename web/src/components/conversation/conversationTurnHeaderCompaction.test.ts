import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import type { AgentMessageSectionState } from "./agentMessageSections";
import { conversationVisualThreadKey, shouldCompactConversationTurnHeader } from "./conversationTurnHeaderCompaction";

const sectionState = { hasProcessSection: true } as AgentMessageSectionState;

function assistant(id: string): ConversationMessage {
  return {
    id,
    role: "assistant",
    timestamp: "2026-08-09T00:00:00Z",
    turnId: "turn-1",
    status: "running",
    turnItems: [{
      id: `${id}-status-r1`, itemId: `${id}-status`, version: 3, sessionId: "session-1", turnId: "turn-1",
      type: "status", code: "model_thinking", text: "思考中", status: "running", revision: 1, sequence: 1,
    }],
  };
}

describe("conversation turn header compaction", () => {
  it("uses the canonical turn id to compact same-turn rows", () => {
    const first = assistant("message-1");
    const second = assistant("message-2");
    expect(conversationVisualThreadKey(first, sectionState)).toBe("assistant-turn:turn-1");
    expect(shouldCompactConversationTurnHeader(first, second, sectionState, sectionState)).toBe(true);
  });
});
