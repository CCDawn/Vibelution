import { describe, expect, it } from "vitest";

import type { SessionStreamEvent } from "../api/types";
import {
  createSessionStreamAppendReassembler,
  routeSessionStreamEvent,
  sessionStreamProtocolTelemetryFields,
} from "./chatSessionStreamProtocol";

type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

function raw(payload: unknown) {
  return JSON.stringify(payload);
}

function assistantDelta(patch: Partial<AssistantDeltaPayload> = {}): AssistantDeltaPayload {
  return {
    type: "assistant_delta",
    sessionId: "session-1",
    turnId: "turn-1",
    ledgerSeq: 8,
    stage: "responding",
    content: "",
    thought: "",
    contentDelta: "",
    thoughtDelta: "",
    replaceContent: false,
    replaceThought: false,
    feedbackEvents: [],
    updatedAt: "2026-07-09T08:00:00Z",
    done: false,
    ...patch,
  };
}

describe("chat session stream protocol router", () => {it("rejects mismatched stream event types with a traceable reason", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "session_detail",
      rawData: raw(assistantDelta({ contentDelta: "hello" })),
    });

    expect(routed.accepted).toBe(false);
    expect(routed.trace).toMatchObject({
      expectedType: "session_detail",
      actualType: "assistant_delta",
      eventRoute: "rejected",
      rejectReason: "event_type_mismatch",
      sessionId: "session-1",
    });
  });

  it("rejects session mismatches before the route can update UI state", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "assistant_delta",
      rawData: raw(assistantDelta({ sessionId: "session-2", contentDelta: "hello" })),
    });

    expect(routed.accepted).toBe(false);
    expect(routed.trace).toMatchObject({
      expectedType: "assistant_delta",
      actualType: "assistant_delta",
      eventRoute: "rejected",
      rejectReason: "session_mismatch",
      sessionId: "session-2",
    });
  });

  it("reports parse failures without throwing from the router", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "session_initial",
      rawData: "{not-json",
    });

    expect(routed.accepted).toBe(false);
    expect(routed.trace).toMatchObject({
      expectedType: "session_initial",
      actualType: "unparseable",
      eventRoute: "rejected",
      rejectReason: "parse_error",
      payloadLength: "{not-json".length,
    });
  });
});

describe("resume protocol routes", () => {
  it("routes the stream_resume marker with its journal window", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "stream_resume",
      eventId: "12",
      rawData: raw({
        type: "stream_resume",
        sessionId: "session-1",
        resume: "replayed",
        fromSeq: 4,
        toSeq: 12,
        replayedCount: 8,
      }),
    });

    expect(routed.accepted).toBe(true);
    expect(routed.trace).toMatchObject({
      eventRoute: "stream_resume",
      sseEventId: 12,
      ledgerSeq: 12,
    });
  });

  it("routes replayed session_journal_event frames", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "session_journal_event",
      eventId: "7",
      rawData: raw({
        type: "session_journal_event",
        sessionId: "session-1",
        seq: 7,
        eventId: "evt-000007",
        turnId: "turn-1",
        eventType: "assistant_item_committed",
        status: "completed",
        timestamp: "2026-10-01T00:00:07Z",
        payload: { n: 7 },
      }),
    });

    expect(routed.accepted).toBe(true);
    expect(routed.trace).toMatchObject({
      eventRoute: "session_journal_event",
      sseEventId: 7,
      ledgerSeq: 7,
    });
    const telemetry = sessionStreamProtocolTelemetryFields(routed.trace);
    expect(telemetry.streamSseEventId).toBe(7);
  });
});

describe("session stream append reassembler", () => {
  type AppendEntry = NonNullable<AssistantDeltaPayload["turnItemAppends"]>[number];

  function appendEntry(patch: Partial<AppendEntry>): AppendEntry {
    return {
      kind: "append",
      itemId: "answer",
      itemType: "agent_message",
      baseLength: 5,
      appendedLength: 6,
      appendedText: " world",
      ...patch,
    };
  }

  function messageItem(text: string, itemId = "answer") {
    return {
      version: 3 as const,
      id: itemId,
      itemId,
      sessionId: "session-1",
      turnId: "turn-1",
      type: "agent_message" as const,
      status: "running" as const,
      phase: "final_answer" as const,
      revision: 1,
      sequence: 1,
      text,
    };
  }

  it("splices append fragments onto the cached full row into a legacy-shaped frame", () => {
    const reassembler = createSessionStreamAppendReassembler();
    const seeded = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 8,
      stage: "responding",
      turnItems: [messageItem("hello")],
      updatedAt: "2026-07-09T08:00:00Z",
      done: false,
    });
    expect(seeded.gaps).toEqual([]);

    const expanded = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 9,
      stage: "responding",
      turnItems: [],
      turnItemAppends: [appendEntry({})],
      updatedAt: "2026-07-09T08:00:01Z",
      done: false,
    });

    expect(expanded.gaps).toEqual([]);
    expect(expanded.payload.turnItemAppends).toBeUndefined();
    expect(expanded.payload.turnItems).toHaveLength(1);
    expect((expanded.payload.turnItems[0] as { text: string }).text).toBe("hello world");
  });

  it("reports a gap instead of guessing when the itemId is unknown", () => {
    const reassembler = createSessionStreamAppendReassembler();
    const expanded = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 9,
      stage: "responding",
      turnItems: [],
      turnItemAppends: [appendEntry({ itemId: "never-seen" })],
      updatedAt: "2026-07-09T08:00:01Z",
      done: false,
    });

    expect(expanded.gaps).toEqual([
      { itemId: "never-seen", baseLength: 5, reason: "unknown_item" },
    ]);
    // Nothing partial is applied: the payload comes back untouched.
    expect(expanded.payload.turnItemAppends).toHaveLength(1);
  });

  it("reports a length mismatch when the cached text diverges from baseLength", () => {
    const reassembler = createSessionStreamAppendReassembler();
    reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 8,
      stage: "responding",
      turnItems: [messageItem("stale")],
      updatedAt: "2026-07-09T08:00:00Z",
      done: false,
    });

    const expanded = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 9,
      stage: "responding",
      turnItems: [],
      turnItemAppends: [appendEntry({ baseLength: 4 })],
      updatedAt: "2026-07-09T08:00:01Z",
      done: false,
    });

    expect(expanded.gaps).toEqual([
      { itemId: "answer", baseLength: 4, reason: "length_mismatch" },
    ]);
  });

  it("reseeds the cache when the turn changes so appends restart clean", () => {
    const reassembler = createSessionStreamAppendReassembler();
    reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 8,
      stage: "responding",
      turnItems: [messageItem("hello")],
      updatedAt: "2026-07-09T08:00:00Z",
      done: false,
    });

    const nextTurn = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-2",
      ledgerSeq: 20,
      stage: "responding",
      turnItems: [messageItem("new turn body", "answer-2")],
      turnItemAppends: [appendEntry({ itemId: "answer" })],
      updatedAt: "2026-07-09T08:01:00Z",
      done: false,
    });

    // The previous turn's item no longer exists in the new turn's cache.
    expect(nextTurn.gaps).toEqual([
      { itemId: "answer", baseLength: 5, reason: "unknown_item" },
    ]);
  });

  it("lets full rows in the same frame win over redundant appends", () => {
    const reassembler = createSessionStreamAppendReassembler();
    reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 8,
      stage: "responding",
      turnItems: [messageItem("hello")],
      updatedAt: "2026-07-09T08:00:00Z",
      done: false,
    });

    const expanded = reassembler.expand({
      type: "assistant_delta",
      sessionId: "session-1",
      turnId: "turn-1",
      ledgerSeq: 9,
      stage: "responding",
      turnItems: [messageItem("hello world fresh")],
      turnItemAppends: [appendEntry({})],
      updatedAt: "2026-07-09T08:00:01Z",
      done: false,
    });

    // The same-frame full row already covers the item: the stale fragment is
    // skipped silently instead of surfacing a false gap.
    expect(expanded.gaps).toEqual([]);
    const texts = expanded.payload.turnItems.map((item) => (item as { text: string }).text);
    expect(texts).toEqual(["hello world fresh"]);
  });
});
