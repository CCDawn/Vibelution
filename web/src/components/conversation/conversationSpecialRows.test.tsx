import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { conversationCompressionDividerTone, conversationCompressionTurnBody } from "./conversationSpecialRows";

const base = {
  version: 3 as const, sessionId: "session-1", turnId: "turn-1", revision: 0,
  sequence: 1, terminal: true, status: "completed" as const,
};

function assistant(turnItems: SessionTurnItem[]): ConversationMessage {
  return { id: "assistant-1", role: "assistant", timestamp: "2026-10-22T00:00:00Z", turnId: base.turnId, status: "completed", turnItems };
}

describe("compression checkpoint display ownership", () => {
  it.each(["applied", "skipped_low_savings", "failed_preserved"] as const)("recognizes %s code-only statuses without swallowing other items", (outcome) => {
    const checkpoint: SessionTurnItem = {
      ...base, id: "checkpoint:0", itemId: "checkpoint", type: "status", code: `context_compression_${outcome}`, text: "bookkeeping",
    };
    const progress: SessionTurnItem = {
      ...base, id: "progress:0", itemId: "progress", type: "status", code: "model_request", text: "connecting", terminal: false,
    };
    const reasoning: SessionTurnItem = {
      ...base, id: "reasoning:0", itemId: "reasoning", type: "reasoning", text: "继续检查证据。",
    };
    const message = assistant([checkpoint, progress, reasoning]);
    const body = conversationCompressionTurnBody(message);
    expect(conversationCompressionDividerTone(message)).toBe(outcome);
    expect(body.turnItems).toEqual([progress, reasoning]);
    expect(body.turnItems[0]).toBe(progress);
    expect(message.turnItems).toEqual([checkpoint, progress, reasoning]);
    expect(conversationCompressionTurnBody(message)).toBe(body);
  });

  it("keeps an ordinary turn unchanged when its text merely mentions compaction", () => {
    const message = assistant([{ ...base, id: "answer:0", itemId: "answer", type: "agent_message", phase: "final_answer", text: "context_compression_applied 是状态名。" }]);
    expect(conversationCompressionDividerTone(message)).toBeNull();
    expect(conversationCompressionTurnBody(message)).toBe(message);
  });

  it("does not treat an in-progress compression status as an outcome checkpoint", () => {
    const message = assistant([{ ...base, id: "status:0", itemId: "status", type: "status", code: "context_compression_started", text: "compressing", status: "running", terminal: false }]);
    expect(conversationCompressionDividerTone(message)).toBeNull();
    expect(conversationCompressionTurnBody(message)).toBe(message);
  });

  it("does not remove a user item carrying the same diagnostic kind", () => {
    const message: ConversationMessage = {
      id: "user-1", role: "user", timestamp: "2026-10-22T00:00:00Z",
      turnItems: [{ ...base, id: "user:0", itemId: "user", type: "status", code: "context_compression_applied", text: "quoted status" }],
    };
    expect(conversationCompressionDividerTone(message)).toBeNull();
    expect(conversationCompressionTurnBody(message)).toBe(message);
  });
});
