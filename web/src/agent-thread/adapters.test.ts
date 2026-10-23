import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../api/types";
import { conversationMessageToAgentMessage } from "./adapters";

function assistantTurn(turnItems: SessionTurnItem[]): ConversationMessage {
  return {
    id: "assistant-turn-1",
    role: "assistant",
    timestamp: "2026-08-10T00:00:00Z",
    turnId: "turn-1",
    status: "completed",
    turnItems,
  };
}

describe("conversationMessageToAgentMessage", () => {
  it("keeps operation order at creation while a prior item receives a later revision", () => {
    const base = { version: 3, sessionId: "session-1", turnId: "turn-1", type: "reasoning", status: "completed", revision: 1 } as const;
    const result = conversationMessageToAgentMessage(assistantTurn([
      { ...base, id: "later", itemId: "later", sequence: 20, text: "later" },
      { ...base, id: "earlier-r2", itemId: "earlier", revision: 2, sequence: 40, metadata: { orderSequence: 10 }, text: "updated" },
    ]));
    expect(result.parts.map((part) => part.id)).toEqual(["earlier-r2", "later"]);
    expect(result.parts.map((part) => part.type === "thought" && part.sequence)).toEqual([10, 20]);
  });

  it("skips malformed persisted reasoning without losing the reachable assistant answer", () => {
    const incompleteReasoning = {
      id: "reasoning-1",
      itemId: "reasoning-1",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "reasoning",
      status: "completed",
      revision: 1,
      sequence: 1,
      // Historical session records may omit text entirely.
    } as unknown as SessionTurnItem;
    const answer: SessionTurnItem = {
      id: "answer-1",
      itemId: "answer-1",
      version: 3,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "agent_message",
      phase: "final_answer",
      text: "可继续处理",
      status: "completed",
      revision: 1,
      sequence: 2,
    };

    const result = conversationMessageToAgentMessage(assistantTurn([incompleteReasoning, answer]));

    expect(result.parts).toEqual([
      expect.objectContaining({
        id: "answer-1",
        type: "text",
        channel: "answer",
        text: "可继续处理",
      }),
    ]);
  });
});
