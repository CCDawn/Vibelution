import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { resolveAssistantDisplayPlan } from "./assistantDisplayPlan";

describe("assistantDisplayPlan canonical ownership", () => {
  it("assigns answer ownership only to turnItems", () => {
    const message: ConversationMessage = {
      id: "message-1",
      role: "assistant",
      timestamp: "2026-08-09T00:00:00Z",
      turnId: "turn-1",
      status: "completed",
      turnItems: [{
        id: "answer-1-r1",
        itemId: "answer-1",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "agent_message",
        phase: "final_answer",
        text: "完成。",
        status: "completed",
        revision: 1,
        sequence: 1,
      }],
    };

    expect(resolveAssistantDisplayPlan({ message })).toMatchObject({
      protocol: "turn_items",
      answerOwner: "canonical_turn_items",
      renderMode: "turn_items",
      suppressProjectedResponse: true,
    });
  });
});
