import { describe, expect, it } from "vitest";

import type { SessionStreamEvent } from "../api/types";
import { createSessionAssistantDeltaScheduler } from "./sessionAssistantDeltaScheduler";

type AssistantDelta = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

function delta(done = false): AssistantDelta {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 1,
    stage: "responding",
    updatedAt: "2026-08-09T00:00:00Z",
    done,
    turnItems: [{
      id: "answer-r1", itemId: "answer", version: 3, sessionId: "session-1", turnId: "turn-1",
      type: "agent_message", phase: "final_answer", text: "完成。", status: done ? "completed" : "running", revision: 1, sequence: 1,
    }],
  };
}

describe("sessionAssistantDeltaScheduler canonical payload", () => {
  it("drains turnItems and reports canonical text length", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 100 });
    scheduler.enqueue(delta(), 120);
    const result = scheduler.drain("frame", { frameScheduledAtMs: 90 });
    expect(result.entries).toHaveLength(1);
    expect(result.telemetry.contentDeltaLength).toBe(3);
    expect(result.entries[0]?.payload).not.toHaveProperty("contentDelta");
  });

  it("treats incomplete live text revisions as zero-length telemetry", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 100 });
    const incomplete: AssistantDelta = {
      ...delta(),
      turnItems: [
        {
          ...delta().turnItems[0],
          text: undefined as unknown as string,
        },
        {
          id: "thought-r1", itemId: "thought", version: 3, sessionId: "session-1", turnId: "turn-1",
          type: "reasoning", text: undefined as unknown as string, status: "running", revision: 1, sequence: 2,
        },
      ],
    };

    scheduler.enqueue(incomplete, 120);
    const result = scheduler.drain("frame", { frameScheduledAtMs: 90 });

    expect(result.telemetry.contentDeltaLength).toBe(0);
    expect(result.telemetry.thoughtDeltaLength).toBe(0);
  });
});
