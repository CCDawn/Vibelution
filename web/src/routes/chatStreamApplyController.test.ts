import { describe, expect, it } from "vitest";

import type { SessionDetail, SessionStreamEvent } from "../api/types";
import type { ActiveTurnLayerState } from "./chatActiveTurnLayer";
import type { SessionStreamProtocolTrace } from "./chatSessionStreamProtocol";
import type { SessionAssistantDeltaDrainResult } from "./sessionAssistantDeltaScheduler";
import {
  planAppliedAssistantDeltaDrain,
  planAppliedSessionDetail,
  planQueuedSessionDetail,
  type SessionStreamApplyStats,
} from "./chatStreamApplyController";

type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

function detail(patch: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: "session-1",
    title: "Session 1",
    status: "running",
    currentPhase: "running",
    agentId: "agent-1",
    agentName: "Agent 1",
    mode: "direct",
    createdAt: "2026-07-09T08:00:00Z",
    updatedAt: "2026-07-09T08:00:00Z",
    messageCount: 0,
    latestMessage: "",
    defaultFileContext: "",
    previewTabs: [],
    activePreviewPath: "",
    changedFiles: [],
    readFiles: [],
    messages: [],
    stopRequested: false,
    stopRequestedAt: "",
    stopReason: "",
    ...patch,
  } as SessionDetail;
}

function trace(patch: Partial<SessionStreamProtocolTrace> = {}): SessionStreamProtocolTrace {
  return {
    expectedType: "session_detail",
    actualType: "session_detail",
    eventRoute: "session_detail",
    payloadLength: 120,
    sessionId: "session-1",
    ledgerSeq: 1,
    turnId: "",
    itemId: "",
    turnItemCount: 0,
    stage: "",
    done: false,
    ...patch,
  };
}

function stats(patch: Partial<SessionStreamApplyStats> = {}): SessionStreamApplyStats {
  return {
    received: 0,
    applied: 0,
    dropped: 0,
    ...patch,
  };
}

function activeLayer(patch: Partial<ActiveTurnLayerState> = {}): ActiveTurnLayerState {
  return {
    id: "session-1-message-active-turn-1",
    sessionId: "session-1",
    turnId: "turn-1",
    updatedAt: "2026-07-09T08:00:00Z",
    streaming: true,
    processStage: "responding",
    answerContent: "live",
    thoughtContent: "",
    feedbackEvents: [],
    ledgerSeq: 1,
    ...patch,
  };
}

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
    updatedAt: "2026-07-09T08:00:00Z",
    done: false,
    ...patch,
  };
}

function drain(
  entries: SessionAssistantDeltaDrainResult["entries"],
  patch: Partial<SessionAssistantDeltaDrainResult> = {},
): SessionAssistantDeltaDrainResult {
  return {
    reason: "frame",
    mode: "smooth",
    entries,
    pendingBefore: entries.length,
    pendingAfter: 0,
    batchSize: entries.length,
    oldestQueuedAgeMs: 0,
    shouldContinue: false,
    telemetry: {
      payloadLength: entries.reduce((total, entry) => total + entry.payloadLength, 0),
      turnId: entries[entries.length - 1]?.payload.turnId ?? "",
      stage: entries[entries.length - 1]?.payload.stage ?? "",
      contentDeltaLength: entries.reduce((total, entry) => total + (entry.payload.contentDelta ?? "").length, 0),
      thoughtDeltaLength: 0,
      batchSize: entries.length,
      done: entries.some((entry) => entry.payload.done),
      oldestReceivedAtMs: 100,
      newestReceivedAtMs: 130,
      frameScheduledAtMs: 90,
      turnRenderProtocol: "legacy_assistant_delta",
    },
    ...patch,
  };
}

describe("chatStreamApplyController", () => {
  it("coalesces queued session detail snapshots and exposes the timer decision", () => {
    const decision = planQueuedSessionDetail({
      detail: detail({ currentPhase: "running" }),
      trace: trace(),
      pendingDetail: detail({ currentPhase: "responding" }),
      stats: stats({ received: 2, applied: 1, dropped: 0 }),
      lastAppliedAtMs: 1_000,
      nowMs: 1_100,
      minApplyIntervalMs: 350,
      isBusyPhase: (phase) => phase === "running" || phase === "responding",
    });

    expect(decision.action).toBe("schedule_timer");
    expect(decision.delayMs).toBe(250);
    expect(decision.pendingDetail.currentPhase).toBe("running");
    expect(decision.stats).toEqual({ received: 3, applied: 1, dropped: 1 });
    expect(decision.shouldLogQueued).toBe(false);
  });

  it("applies final session detail snapshots immediately and clears active layers by reason", () => {
    const queued = planQueuedSessionDetail({
      detail: detail({ currentPhase: "completed", status: "completed" }),
      trace: trace({ ledgerSeq: 8 }),
      pendingDetail: null,
      stats: stats(),
      lastAppliedAtMs: 1_000,
      nowMs: 1_010,
      minApplyIntervalMs: 350,
      isBusyPhase: (phase) => phase === "running",
    });

    expect(queued.action).toBe("apply_now");
    expect(queued.applyReason).toBe("final");

    const applied = planAppliedSessionDetail({
      streamSessionId: "session-1",
      reason: "final",
      detail: queued.pendingDetail,
      trace: queued.pendingDetailTrace,
      stats: queued.stats,
      activeLayer: activeLayer(),
      activeLayerSettled: false,
      isBusyPhase: (phase) => phase === "running",
    });

    expect(applied.stats).toEqual({ received: 1, applied: 1, dropped: 0 });
    expect(applied.clearActiveLayer).toBe(true);
    expect(applied.clearActiveLayerReason).toBe("final_phase");
    expect(applied.shouldLogApplied).toBe(true);
    expect(applied.telemetry).toMatchObject({
      sessionId: "session-1",
      reason: "final",
      receivedCount: 1,
      appliedCount: 1,
      droppedCount: 0,
      currentPhase: "completed",
      streamLedgerSeq: 8,
    });
  });

  it("clears active layers when committed detail settles the same turn even while busy", () => {
    const applied = planAppliedSessionDetail({
      streamSessionId: "session-1",
      reason: "timer",
      detail: detail({ currentPhase: "running" }),
      trace: trace(),
      stats: stats({ received: 1, applied: 1, dropped: 0 }),
      activeLayer: activeLayer(),
      activeLayerSettled: true,
      isBusyPhase: (phase) => phase === "running",
    });

    expect(applied.clearActiveLayer).toBe(true);
    expect(applied.clearActiveLayerReason).toBe("committed_detail");
  });

  it("applies assistant delta drains with explicit telemetry and final invalidation", () => {
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "final",
      drain: drain([
        {
          payload: assistantDelta({ contentDelta: "A" }),
          payloadLength: 10,
          receivedAtMs: 100,
        },
        {
          payload: assistantDelta({ contentDelta: "B", done: true }),
          payloadLength: 11,
          receivedAtMs: 130,
        },
      ], {
        reason: "final",
        mode: "final",
      }),
      committedLayer: undefined,
      stats: stats({ received: 2, applied: 0, dropped: 0 }),
      applyStartedAtMs: 150,
      applyFinishedAtMs: 155,
    });

    expect(decision.applied).toBe(true);
    if (!decision.applied) {
      throw new Error("expected assistant delta drain to apply");
    }
    expect(decision.nextCommittedLayer?.answerContent).toBe("AB");
    expect(decision.stats).toEqual({ received: 2, applied: 1, dropped: 0 });
    expect(decision.shouldInvalidateSession).toBe(true);
    expect(decision.shouldScheduleNextFrame).toBe(false);
    expect(decision.shouldLogApplied).toBe(true);
    expect(decision.telemetry).toMatchObject({
      sessionId: "session-1",
      reason: "final",
      pendingTextLength: 2,
      payloadLength: 21,
      batchSize: 2,
      done: true,
      drainMode: "final",
      receivedToApplyMs: 50,
      queuedForMs: 20,
      frameLagMs: 60,
      applyElapsedMs: 5,
    });
  });

  it("keeps frame drains resumable without invalidating session detail", () => {
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: drain([
        {
          payload: assistantDelta({ contentDelta: "A" }),
          payloadLength: 10,
          receivedAtMs: 100,
        },
      ], {
        pendingAfter: 1,
        shouldContinue: true,
      }),
      committedLayer: undefined,
      stats: stats({ received: 2, applied: 49, dropped: 0 }),
      applyStartedAtMs: 150,
      applyFinishedAtMs: 152,
    });

    expect(decision.applied).toBe(true);
    if (!decision.applied) {
      throw new Error("expected assistant delta drain to apply");
    }
    expect(decision.shouldScheduleNextFrame).toBe(true);
    expect(decision.shouldInvalidateSession).toBe(false);
    expect(decision.shouldLogApplied).toBe(true);
    expect(decision.telemetry.appliedCount).toBe(50);
  });
});
