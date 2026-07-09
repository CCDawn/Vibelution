import { describe, expect, it } from "vitest";

import type { SessionStreamEvent } from "../api/types";
import {
  createSessionAssistantDeltaScheduler,
  type SessionAssistantDeltaDrainMode,
} from "./sessionAssistantDeltaScheduler";

type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

function assistantDelta(patch: Partial<AssistantDeltaPayload> = {}): AssistantDeltaPayload {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 1,
    stage: "responding",
    content: "",
    thought: "",
    contentDelta: "",
    thoughtDelta: "",
    replaceContent: false,
    replaceThought: false,
    feedbackEvents: [],
    updatedAt: "2026-07-07T08:00:00Z",
    done: false,
    ...patch,
  };
}

describe("sessionAssistantDeltaScheduler", () => {
  it("drains one assistant delta per browser frame while queue pressure is low", () => {
    let nowMs = 0;
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => nowMs });

    scheduler.enqueue(assistantDelta({ contentDelta: "你" }), 120);
    scheduler.enqueue(assistantDelta({ contentDelta: "好" }), 121);
    scheduler.enqueue(assistantDelta({ contentDelta: "。" }), 122);

    nowMs = 16;
    const first = scheduler.drain("frame", { frameScheduledAtMs: 4 });

    expect(first.mode).toBe("smooth" satisfies SessionAssistantDeltaDrainMode);
    expect(first.entries.map((entry) => entry.payload.contentDelta)).toEqual(["你"]);
    expect(first.batchSize).toBe(1);
    expect(first.pendingBefore).toBe(3);
    expect(first.pendingAfter).toBe(2);
    expect(first.shouldContinue).toBe(true);
    expect(first.telemetry).toMatchObject({
      payloadLength: 120,
      contentDeltaLength: 1,
      thoughtDeltaLength: 0,
      batchSize: 1,
      done: false,
      frameScheduledAtMs: 4,
    });
  });

  it("drains the full backlog once queued assistant deltas reach the catch-up depth", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 0 });

    for (let index = 0; index < 8; index += 1) {
      scheduler.enqueue(assistantDelta({ contentDelta: String(index) }), 10 + index);
    }

    const drain = scheduler.drain("frame", { frameScheduledAtMs: 8 });

    expect(drain.mode).toBe("catch_up");
    expect(drain.entries).toHaveLength(8);
    expect(drain.entries.map((entry) => entry.payload.contentDelta).join("")).toBe("01234567");
    expect(drain.pendingAfter).toBe(0);
    expect(drain.shouldContinue).toBe(false);
    expect(drain.telemetry.batchSize).toBe(8);
    expect(drain.telemetry.payloadLength).toBe(108);
  });

  it("drains the full backlog when the oldest queued assistant delta has waited too long", () => {
    let nowMs = 0;
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => nowMs });

    scheduler.enqueue(assistantDelta({ contentDelta: "慢" }), 80);
    scheduler.enqueue(assistantDelta({ contentDelta: "了" }), 81);

    nowMs = 121;
    const drain = scheduler.drain("frame", { frameScheduledAtMs: 100 });

    expect(drain.mode).toBe("catch_up");
    expect(drain.entries.map((entry) => entry.payload.contentDelta)).toEqual(["慢", "了"]);
    expect(drain.oldestQueuedAgeMs).toBe(121);
    expect(drain.pendingAfter).toBe(0);
  });

  it("flushes pending assistant deltas immediately for final or close drains", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 20 });

    scheduler.enqueue(assistantDelta({ contentDelta: "收" }), 60);
    scheduler.enqueue(assistantDelta({ contentDelta: "尾", done: true }), 61);

    const drain = scheduler.drain("final", { frameScheduledAtMs: 0 });

    expect(drain.mode).toBe("final");
    expect(drain.entries.map((entry) => entry.payload.contentDelta)).toEqual(["收", "尾"]);
    expect(drain.telemetry.done).toBe(true);
    expect(drain.pendingAfter).toBe(0);
  });

  it("preserves native Codex transcript snapshots without counting them as text delta", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 0 });
    const payload = assistantDelta({
      contentDelta: "",
      thoughtDelta: "",
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "session-1-message-live-turn-1",
        cells: [
          {
            id: "native-tool",
            kind: "tool_call",
            messageId: "session-1-message-live-turn-1",
            status: "running",
            tone: "running",
            title: "npm build",
          },
        ],
      },
    });

    scheduler.enqueue(payload, 4096);
    const drain = scheduler.drain("frame");

    expect(drain.entries[0].payload.codexTranscript?.source).toBe("native");
    expect(drain.entries[0].payload.codexTranscript?.cells[0]?.id).toBe("native-tool");
    expect(drain.telemetry.payloadLength).toBe(4096);
    expect(drain.telemetry.contentDeltaLength).toBe(0);
    expect(drain.telemetry.thoughtDeltaLength).toBe(0);
  });

  it("carries stream protocol trace through assistant delta drains", () => {
    const scheduler = createSessionAssistantDeltaScheduler({ nowMs: () => 0 });

    scheduler.enqueue(assistantDelta({ contentDelta: "回答" }), 80, {
      expectedType: "assistant_delta",
      actualType: "assistant_delta",
      eventRoute: "assistant_delta",
      turnRenderProtocol: "legacy_assistant_delta",
      payloadLength: 80,
      sessionId: "session-1",
      ledgerSeq: 1,
      turnId: "turn-1",
      stage: "responding",
      done: false,
    });

    const drain = scheduler.drain("frame");

    expect(drain.telemetry.turnRenderProtocol).toBe("legacy_assistant_delta");
  });
});
