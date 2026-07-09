import { describe, expect, it } from "vitest";

import type { SessionStreamEvent } from "../api/types";
import {
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

describe("chat session stream protocol router", () => {
  it("routes native assistant delta payloads with explicit protocol trace", () => {
    const routed = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "assistant_delta",
      rawData: raw(assistantDelta({
        contentDelta: "",
        codexTranscript: {
          version: 1,
          source: "native",
          messageId: "session-1-message-live-turn-1",
          cells: [
            {
              id: "native-answer",
              kind: "assistant_markdown",
              messageId: "session-1-message-live-turn-1",
              status: "completed",
              tone: "neutral",
              text: "native answer",
            },
          ],
        },
      })),
    });

    expect(routed.accepted).toBe(true);
    if (!routed.accepted) {
      throw new Error("expected accepted route");
    }
    expect(routed.payload.type).toBe("assistant_delta");
    expect(routed.trace).toMatchObject({
      expectedType: "assistant_delta",
      actualType: "assistant_delta",
      eventRoute: "assistant_delta",
      turnRenderProtocol: "native_codex_transcript",
      sessionId: "session-1",
      turnId: "turn-1",
      stage: "responding",
      ledgerSeq: 8,
      done: false,
    });
    expect(sessionStreamProtocolTelemetryFields(routed.trace)).toMatchObject({
      streamExpectedType: "assistant_delta",
      streamActualType: "assistant_delta",
      streamEventRoute: "assistant_delta",
      turnRenderProtocol: "native_codex_transcript",
      streamRejectReason: "",
    });
  });

  it("routes legacy assistant deltas separately from process feedback", () => {
    const legacy = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "assistant_delta",
      rawData: raw(assistantDelta({ contentDelta: "hello" })),
    });
    const processOnly = routeSessionStreamEvent({
      activeSessionId: "session-1",
      expectedType: "assistant_delta",
      rawData: raw(assistantDelta({
        contentDelta: "",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_request",
            summary: "正在请求模型",
          },
        ],
      })),
    });

    expect(legacy.accepted && legacy.trace.turnRenderProtocol).toBe("legacy_assistant_delta");
    expect(processOnly.accepted && processOnly.trace.turnRenderProtocol).toBe("process_feedback");
  });

  it("rejects mismatched stream event types with a traceable reason", () => {
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
