import { describe, expect, it } from "vitest";

import type { SessionDetail, SessionStreamEvent, SessionTurnItem } from "../api/types";
import {
  mergeAssistantDeltaIntoActiveTurnLayer,
  reconcileActiveTurnLayerItemsWithMessages,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";
import {
  planAppliedAssistantDeltaDrain,
  type SessionStreamApplyStats,
} from "./chatStreamApplyController";
import {
  createAssistantDeltaSeqGate,
  createSessionStreamRecoveryController,
  resolveSessionStreamRecoveryDelayMs,
  SESSION_STREAM_RECOVERY_BACKOFF_MS,
  type SessionStreamRecoveryController,
} from "./chatStreamProjectionGate";
import type { SessionAssistantDeltaDrainResult } from "./sessionAssistantDeltaScheduler";

type AssistantDeltaPayload = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

function delta(patch: Partial<AssistantDeltaPayload>): AssistantDeltaPayload {
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
    updatedAt: "2026-09-24T08:30:00Z",
    done: false,
    ...patch,
  };
}

describe("assistant delta seq continuity gate (projection invariant a)", () => {
  it("applies a dense ledger advance", () => {
    const gate = createAssistantDeltaSeqGate();
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 4 })).toMatchObject({ action: "apply", seq: 4 });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 5 })).toMatchObject({ action: "apply", seq: 5 });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 6 })).toMatchObject({ action: "apply", seq: 6 });
  });

  it("applies a same-epoch coalesced frame (full turn projection, same ledger seq)", () => {
    const gate = createAssistantDeltaSeqGate();
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 4 })).toMatchObject({ action: "apply" });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 4 })).toMatchObject({ action: "apply" });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 4 })).toMatchObject({ action: "apply" });
    expect(gate.lastAppliedSeq).toBe(4);
  });

  it("drops stale out-of-order regressions", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 6 });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 5 })).toMatchObject({
      action: "drop-stale",
      seq: 5,
      lastAppliedSeq: 6,
    });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 6 })).toMatchObject({ action: "apply" });
  });

  it("holds a sparse ledger jump instead of applying it", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 4 });
    const decision = gate.decide({ turnId: "turn-1", ledgerSeq: 7 });
    expect(decision).toMatchObject({
      action: "hold-gap",
      seq: 7,
      lastAppliedSeq: 4,
      watermark: 5,
    });
    // Held frames do not move the baseline.
    expect(gate.lastAppliedSeq).toBe(4);
  });

  it("applies legacy frames without ledger bookkeeping ungated", () => {
    const gate = createAssistantDeltaSeqGate();
    expect(gate.decide({ turnId: "turn-1" })).toMatchObject({ action: "apply" });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 0 })).toMatchObject({ action: "apply" });
    expect(gate.lastAppliedSeq).toBe(0);
  });

  it("re-baselines on a new turn id", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 9 });
    expect(gate.decide({ turnId: "turn-2", ledgerSeq: 10 })).toMatchObject({
      action: "apply",
      firstFrameOfTurn: true,
    });
    expect(gate.lastAppliedSeq).toBe(10);
  });

  it("advances to an authoritative watermark without regressing behind applied deltas", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 6 });
    gate.noteAuthoritative(9);
    expect(gate.lastAppliedSeq).toBe(9);
    gate.noteAuthoritative(4);
    expect(gate.lastAppliedSeq).toBe(9);
    // A frame at the authoritative watermark applies instead of holding.
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 9 })).toMatchObject({ action: "apply" });
  });

  it("re-baselines after a stream reopen so the first resumed frame applies", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 4 });
    gate.noteStreamReopened();
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 12 })).toMatchObject({
      action: "apply",
      firstFrameOfTurn: true,
    });
  });

  it("resumes a held stream once the authoritative snapshot reaches the watermark", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 4 });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 8 })).toMatchObject({ action: "hold-gap" });
    // Authoritative snapshot closes the gap at seq 8.
    gate.noteAuthoritative(8);
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 8 })).toMatchObject({ action: "apply" });
    expect(gate.decide({ turnId: "turn-1", ledgerSeq: 9 })).toMatchObject({ action: "apply" });
  });
});

describe("watermark recovery controller (projection invariant b)", () => {
  type Scheduled = { delayMs: number; callback: () => void; cancelled: boolean };
  function harness() {
    const scheduled: Scheduled[] = [];
    const requests: Array<{ watermark: number; attempt: number }> = [];
    let controller: SessionStreamRecoveryController;
    controller = createSessionStreamRecoveryController({
      requestRecovery: ({ watermark, attempt }) => {
        requests.push({ watermark, attempt });
      },
      scheduleDelay: (delayMs, callback) => {
        const entry: Scheduled = { delayMs, callback, cancelled: false };
        scheduled.push(entry);
        return () => {
          entry.cancelled = true;
        };
      },
    });
    return { scheduled, requests, controller };
  }

  it("schedules the first attempt after 200ms and stays single-flight", () => {
    const { scheduled, requests, controller } = harness();
    controller.request(5);
    controller.request(6);
    controller.request(7);
    expect(scheduled).toHaveLength(1);
    expect(scheduled[0]?.delayMs).toBe(200);
    expect(controller.state()).toMatchObject({
      inFlight: true,
      watermark: 7,
      singleFlightSuppressed: 2,
    });
    scheduled[0]?.callback();
    expect(requests).toEqual([{ watermark: 7, attempt: 1 }]);
    expect(controller.state()).toMatchObject({ inFlight: false, attempt: 1 });
    controller.dispose();
  });

  it("walks the exponential backoff ladder capped at 5s", () => {
    expect(SESSION_STREAM_RECOVERY_BACKOFF_MS).toEqual([200, 400, 800, 1600, 5000]);
    expect(resolveSessionStreamRecoveryDelayMs(0)).toBe(200);
    expect(resolveSessionStreamRecoveryDelayMs(3)).toBe(1600);
    expect(resolveSessionStreamRecoveryDelayMs(9)).toBe(5000);
    const { scheduled, controller } = harness();
    controller.request(3);
    scheduled[0]?.callback();
    controller.request(4);
    scheduled[1]?.callback();
    controller.request(5);
    expect(scheduled.map((entry) => entry.delayMs)).toEqual([200, 400, 800]);
    controller.dispose();
  });

  it("completes when an authoritative seq reaches the watermark and resets attempts", () => {
    const { scheduled, requests, controller } = harness();
    controller.request(5);
    controller.noteAuthoritative(4);
    expect(controller.state().inFlight).toBe(true);
    controller.noteAuthoritative(5);
    expect(controller.state()).toMatchObject({ inFlight: false, attempt: 0, watermark: 5 });
    // The pending attempt timer is retired: firing it must not re-request.
    const stillScheduled = scheduled.filter((entry) => !entry.cancelled);
    stillScheduled.forEach((entry) => entry.callback());
    expect(requests).toHaveLength(0);
    controller.dispose();
  });

  it("retires the episode on a stream reopen", () => {
    const { scheduled, requests, controller } = harness();
    controller.request(5);
    controller.noteStreamReopened();
    expect(controller.state()).toMatchObject({ inFlight: false, attempt: 0 });
    scheduled.filter((entry) => !entry.cancelled).forEach((entry) => entry.callback());
    expect(requests).toHaveLength(0);
    controller.dispose();
  });

  it("dispose cancels the pending attempt", () => {
    const { scheduled, requests, controller } = harness();
    controller.request(2);
    controller.dispose();
    scheduled.forEach((entry) => {
      if (!entry.cancelled) entry.callback();
    });
    expect(requests).toHaveLength(0);
  });
});

describe("drain gating through the projection gate", () => {
  function drainOf(payloads: AssistantDeltaPayload[]): SessionAssistantDeltaDrainResult {
    return {
      reason: "frame",
      mode: "catch_up",
      entries: payloads.map((payload) => ({
        payload,
        payloadLength: 16,
        receivedAtMs: 100,
      })),
      pendingBefore: payloads.length,
      pendingAfter: 0,
      batchSize: payloads.length,
      oldestQueuedAgeMs: 0,
      shouldContinue: false,
      telemetry: {
        payloadLength: 16 * payloads.length,
        turnId: payloads[payloads.length - 1]?.turnId ?? "",
        stage: "responding",
        contentDeltaLength: 0,
        thoughtDeltaLength: 0,
        batchSize: payloads.length,
        done: payloads.some((payload) => payload.done),
        oldestReceivedAtMs: 100,
        newestReceivedAtMs: 100,
        frameScheduledAtMs: 90,
        turnRenderProtocol: "",
      },
    };
  }

  it("keeps ungated drains byte-compatible with the previous merge loop", () => {
    const layer = mergeAssistantDeltaIntoActiveTurnLayer(undefined, delta({
      contentDelta: "hello",
      turnItems: [],
    }));
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: drainOf([delta({ contentDelta: "hello" })]),
      committedLayer: layer,
      stats: { received: 2, applied: 1, dropped: 0 },
      applyStartedAtMs: 100,
    });
    expect(decision.applied).toBe(true);
    if (decision.applied) {
      expect(decision.hold).toBeUndefined();
    }
  });

  it("holds the gap frame and every entry behind it, reporting the watermark", () => {
    const gate = createAssistantDeltaSeqGate();
    const stats: SessionStreamApplyStats = { received: 4, applied: 2, dropped: 0 };
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: drainOf([
        delta({ ledgerSeq: 4 }),
        delta({ ledgerSeq: 9, contentDelta: "later" }),
        delta({ ledgerSeq: 9, contentDelta: "later" }),
      ]),
      committedLayer: undefined,
      stats,
      applyStartedAtMs: 100,
      assistantDeltaSeqGate: (payload) => gate.decide(payload),
    });
    expect(decision.applied).toBe(true);
    if (!decision.applied) {
      return;
    }
    expect(decision.appliedPayloadCount).toBe(1);
    expect(decision.hold).toMatchObject({ heldLedgerSeq: 9, watermark: 5, heldCount: 2 });
    expect(decision.stats).toMatchObject({ received: 4, applied: 3, dropped: 2 });
    expect(decision.nextCommittedLayer?.ledgerSeq).toBe(4);
  });

  it("drops stale frames before merge and applies the rest", () => {
    const gate = createAssistantDeltaSeqGate();
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: drainOf([
        delta({ ledgerSeq: 6, contentDelta: "a" }),
        delta({ ledgerSeq: 3, contentDelta: "stale" }),
        delta({ ledgerSeq: 7, contentDelta: "b" }),
      ]),
      committedLayer: undefined,
      stats: { received: 3, applied: 0, dropped: 0 },
      applyStartedAtMs: 100,
      assistantDeltaSeqGate: (payload) => gate.decide(payload),
    });
    expect(decision.applied).toBe(true);
    if (!decision.applied) {
      return;
    }
    expect(decision.appliedPayloadCount).toBe(2);
    expect(decision.hold).toBeUndefined();
    expect(decision.nextCommittedLayer?.ledgerSeq).toBe(7);
  });

  it("returns a pure hold decision when the first frame of the drain gaps", () => {
    const gate = createAssistantDeltaSeqGate();
    gate.decide({ turnId: "turn-1", ledgerSeq: 4 });
    const stats: SessionStreamApplyStats = { received: 2, applied: 1, dropped: 0 };
    const decision = planAppliedAssistantDeltaDrain({
      streamSessionId: "session-1",
      reason: "frame",
      drain: drainOf([delta({ ledgerSeq: 12, contentDelta: "gap" })]),
      committedLayer: undefined,
      stats,
      applyStartedAtMs: 100,
      assistantDeltaSeqGate: (payload) => gate.decide(payload),
    });
    expect(decision.applied).toBe(false);
    if (decision.applied) {
      return;
    }
    expect(decision.hold).toMatchObject({ heldLedgerSeq: 12, watermark: 5, heldCount: 1 });
    expect(decision.stats.dropped).toBe(1);
  });
});

describe("optimistic overlay per-item reconciliation (projection invariant c)", () => {
  function overlayLayer(turnItems: ActiveTurnLayerState["turnItems"]): ActiveTurnLayerState {
    return {
      id: "session-1-message-active-turn-1",
      sessionId: "session-1",
      turnId: "turn-1",
      updatedAt: "2026-09-24T08:30:00Z",
      status: "running",
      processStage: "responding",
      turnItems,
      ledgerSeq: 4,
    };
  }

  function committedAssistantMessage(turnItems: SessionTurnItem[]) {
    return {
      id: "message-authoritative-1",
      role: "assistant" as const,
      content: "final answer",
      timestamp: "2026-09-24T08:31:00Z",
      turnId: "turn-1",
      status: "completed" as const,
      turnItems,
    };
  }

  it("drops overlay items the authority already committed at an equal revision", () => {
    const overlayTool = {
      type: "tool_call" as const,
      id: "tool-live-1",
      callId: "call-1",
      toolName: "terminal",
      status: "completed" as const,
      revision: 2,
      sequence: 1,
    };
    const authoritativeTool = {
      type: "tool_call" as const,
      id: "tool-canonical-1",
      callId: "call-1",
      toolName: "terminal",
      status: "completed" as const,
      revision: 2,
      sequence: 1,
    };
    const reconciled = reconcileActiveTurnLayerItemsWithMessages(
      overlayLayer([overlayTool, {
        type: "agent_message" as const,
        id: "msg-live-1",
        text: "",
        status: "running" as const,
        revision: 3,
        sequence: 2,
      }]),
      [committedAssistantMessage([authoritativeTool])],
    );
    expect(reconciled?.turnItems).toHaveLength(1);
    expect(reconciled?.turnItems[0]).toMatchObject({ id: "msg-live-1" });
  });

  it("keeps overlay items newer than the authority and unknown identities", () => {
    const overlayItem = {
      type: "tool_call" as const,
      id: "tool-live-2",
      callId: "call-2",
      toolName: "terminal",
      status: "running" as const,
      revision: 5,
      sequence: 1,
    };
    const staleAuthoritative = {
      type: "tool_call" as const,
      id: "tool-canonical-2",
      callId: "call-2",
      toolName: "terminal",
      status: "completed" as const,
      revision: 3,
      sequence: 1,
    };
    const reconciled = reconcileActiveTurnLayerItemsWithMessages(
      overlayLayer([overlayItem]),
      [committedAssistantMessage([staleAuthoritative, {
        type: "reasoning" as const,
        id: "reasoning-1",
        text: "thinking",
        status: "completed" as const,
        revision: 1,
        sequence: 0,
      }])],
    );
    expect(reconciled?.turnItems).toHaveLength(1);
    expect(reconciled?.turnItems[0]).toMatchObject({ id: "tool-live-2" });
  });

  it("keeps the overlay untouched when the authority has nothing for the turn", () => {
    const layer = overlayLayer([{
      type: "agent_message" as const,
      id: "msg-live-3",
      text: "streaming",
      status: "running" as const,
      revision: 1,
      sequence: 0,
    }]);
    expect(reconcileActiveTurnLayerItemsWithMessages(layer, [])).toBe(layer);
    expect(reconcileActiveTurnLayerItemsWithMessages(layer, [
      committedAssistantMessage([]),
    ])).toBe(layer);
  });

  it("keeps the streaming shell when every overlay item was reconciled", () => {
    const overlayItem = {
      type: "tool_call" as const,
      id: "tool-live-4",
      callId: "call-4",
      toolName: "terminal",
      status: "completed" as const,
      revision: 2,
      sequence: 0,
    };
    const reconciled = reconcileActiveTurnLayerItemsWithMessages(
      overlayLayer([overlayItem]),
      [committedAssistantMessage([{
        type: "tool_call" as const,
        id: "tool-canonical-4",
        callId: "call-4",
        toolName: "terminal",
        status: "completed" as const,
        revision: 2,
        sequence: 0,
      }])],
    );
    expect(reconciled).toBeDefined();
    expect(reconciled?.turnItems).toHaveLength(0);
    expect(reconciled?.processStage).toBe("responding");
  });

  it("ignores the overlay projection of itself inside the authoritative messages", () => {
    const layer = overlayLayer([{
      type: "agent_message" as const,
      id: "msg-live-5",
      text: "streaming",
      status: "running" as const,
      revision: 1,
      sequence: 0,
    }]);
    const overlayEcho = {
      id: "session-1-message-active-turn-1",
      role: "assistant" as const,
      content: "",
      timestamp: "2026-09-24T08:30:00Z",
      turnId: "turn-1",
      status: "running" as const,
      turnItems: layer.turnItems,
      metadata: { kind: "session_active_turn_layer" },
    };
    expect(reconcileActiveTurnLayerItemsWithMessages(layer, [overlayEcho])).toBe(layer);
  });
});
