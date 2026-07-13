import type { SessionDetail } from "../api/types";
import {
  activeTurnLayerTextLength,
  mergeAssistantDeltaIntoActiveTurnLayer,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";
import {
  canonicalItemCounts,
  sessionStreamProtocolTelemetryFields,
  type SessionStreamProtocolTrace,
} from "./chatSessionStreamProtocol";
import type {
  SessionAssistantDeltaDrainReason,
  SessionAssistantDeltaDrainResult,
} from "./sessionAssistantDeltaScheduler";

export type SessionStreamApplyStats = {
  received: number;
  applied: number;
  dropped: number;
};

export type SessionDetailApplyReason = "timer" | "close" | "final";

export type PlanQueuedSessionDetailInput = {
  detail: SessionDetail;
  trace: SessionStreamProtocolTrace;
  pendingDetail: SessionDetail | null;
  stats: SessionStreamApplyStats | undefined;
  lastAppliedAtMs: number;
  nowMs: number;
  minApplyIntervalMs: number;
  isBusyPhase: (phase: string) => boolean;
};

export type QueuedSessionDetailDecision = {
  action: "schedule_timer" | "apply_now";
  applyReason?: SessionDetailApplyReason;
  delayMs: number;
  pendingDetail: SessionDetail;
  pendingDetailTrace: SessionStreamProtocolTrace;
  stats: SessionStreamApplyStats;
  shouldLogQueued: boolean;
  telemetry: Record<string, unknown>;
};

export type PlanAppliedSessionDetailInput = {
  streamSessionId: string;
  reason: SessionDetailApplyReason;
  detail: SessionDetail;
  trace: SessionStreamProtocolTrace | null;
  stats: SessionStreamApplyStats | undefined;
  activeLayer: ActiveTurnLayerState | undefined;
  activeLayerSettled: boolean;
  isBusyPhase: (phase: string) => boolean;
};

export type AppliedSessionDetailDecision = {
  stats: SessionStreamApplyStats;
  shouldLogApplied: boolean;
  clearActiveLayer: boolean;
  clearActiveLayerReason: "committed_detail" | "final_phase" | "";
  telemetry: Record<string, unknown>;
};

export type PlanAppliedAssistantDeltaDrainInput = {
  streamSessionId: string;
  reason: SessionAssistantDeltaDrainReason;
  drain: SessionAssistantDeltaDrainResult;
  committedLayer: ActiveTurnLayerState | undefined;
  stats: SessionStreamApplyStats | undefined;
  applyStartedAtMs: number;
  applyFinishedAtMs?: number;
  nowMs?: () => number;
};

export type AppliedAssistantDeltaDrainDecision =
  | {
    applied: false;
    stats: SessionStreamApplyStats;
    appliedPayloadCount: 0;
    shouldLogApplied: false;
    shouldScheduleNextFrame: false;
    shouldInvalidateSession: false;
  }
  | {
    applied: true;
    nextCommittedLayer: ActiveTurnLayerState | undefined;
    stats: SessionStreamApplyStats;
    appliedPayloadCount: number;
    finalDone: boolean;
    shouldLogApplied: boolean;
    shouldScheduleNextFrame: boolean;
    shouldInvalidateSession: boolean;
    lastAppliedAtMs: number;
    telemetry: Record<string, unknown>;
  };

export function normalizeSessionStreamApplyStats(
  stats: SessionStreamApplyStats | undefined,
): SessionStreamApplyStats {
  return {
    received: Math.max(0, Number(stats?.received ?? 0)),
    applied: Math.max(0, Number(stats?.applied ?? 0)),
    dropped: Math.max(0, Number(stats?.dropped ?? 0)),
  };
}

export function planQueuedSessionDetail(
  input: PlanQueuedSessionDetailInput,
): QueuedSessionDetailDecision {
  const nextStats = normalizeSessionStreamApplyStats(input.stats);
  nextStats.received += 1;
  if (input.pendingDetail) {
    nextStats.dropped += 1;
  }

  const finalPhase = isFinalSessionDetailPhase(input.detail, input.isBusyPhase);
  const elapsedMs = Math.max(0, input.nowMs - input.lastAppliedAtMs);
  const delayMs = finalPhase ? 0 : Math.max(0, input.minApplyIntervalMs - elapsedMs);
  const shouldLogQueued = !finalPhase && (nextStats.received === 1 || nextStats.received % 20 === 0);

  return {
    action: finalPhase ? "apply_now" : "schedule_timer",
    applyReason: finalPhase ? "final" : undefined,
    delayMs,
    pendingDetail: input.detail,
    pendingDetailTrace: input.trace,
    stats: nextStats,
    shouldLogQueued,
    telemetry: {
      receivedCount: nextStats.received,
      appliedCount: nextStats.applied,
      droppedCount: nextStats.dropped,
      payloadLength: input.trace.payloadLength,
      messageCount: input.detail.messages?.length ?? 0,
      currentPhase: sessionDetailPhase(input.detail),
      minApplyIntervalMs: input.minApplyIntervalMs,
      ...sessionStreamProtocolTelemetryFields(input.trace),
    },
  };
}

export function planAppliedSessionDetail(
  input: PlanAppliedSessionDetailInput,
): AppliedSessionDetailDecision {
  const nextStats = normalizeSessionStreamApplyStats(input.stats);
  nextStats.applied += 1;

  const finalPhase = isFinalSessionDetailPhase(input.detail, input.isBusyPhase);
  const clearByCommittedDetail = Boolean(input.activeLayer && input.activeLayerSettled);
  const clearActiveLayer = clearByCommittedDetail || finalPhase;
  const clearActiveLayerReason = clearByCommittedDetail
    ? "committed_detail"
    : finalPhase
      ? "final_phase"
      : "";

  return {
    stats: nextStats,
    shouldLogApplied: nextStats.applied === 1 || (nextStats.dropped > 0 && nextStats.applied % 20 === 0),
    clearActiveLayer,
    clearActiveLayerReason,
    telemetry: {
      sessionId: input.streamSessionId,
      reason: input.reason,
      receivedCount: nextStats.received,
      appliedCount: nextStats.applied,
      droppedCount: nextStats.dropped,
      messageCount: input.detail.messages?.length ?? 0,
      currentPhase: sessionDetailPhase(input.detail),
      ...(input.trace ? sessionStreamProtocolTelemetryFields(input.trace) : {}),
    },
  };
}

export function planAppliedAssistantDeltaDrain(
  input: PlanAppliedAssistantDeltaDrainInput,
): AppliedAssistantDeltaDrainDecision {
  let pendingLayer = input.committedLayer;
  let appliedPayloadCount = 0;
  let finalDone = false;
  for (const entry of input.drain.entries) {
    pendingLayer = mergeAssistantDeltaIntoActiveTurnLayer(pendingLayer, entry.payload);
    appliedPayloadCount += 1;
    finalDone = finalDone || entry.payload.done;
  }

  const currentStats = normalizeSessionStreamApplyStats(input.stats);
  if (appliedPayloadCount === 0) {
    return {
      applied: false,
      stats: currentStats,
      appliedPayloadCount: 0,
      shouldLogApplied: false,
      shouldScheduleNextFrame: false,
      shouldInvalidateSession: false,
    };
  }

  const nextStats = {
    ...currentStats,
    applied: currentStats.applied + 1,
  };
  const applyFinishedAtMs = input.applyFinishedAtMs ?? input.nowMs?.() ?? input.applyStartedAtMs;
  const telemetry = assistantDeltaApplyTelemetry({
    streamSessionId: input.streamSessionId,
    reason: input.reason,
    drain: input.drain,
    stats: nextStats,
    appliedPayloadCount,
    pendingLayer,
    applyStartedAtMs: input.applyStartedAtMs,
    applyFinishedAtMs,
  });

  return {
    applied: true,
    nextCommittedLayer: pendingLayer,
    stats: nextStats,
    appliedPayloadCount,
    finalDone,
    shouldLogApplied: nextStats.applied === 1 || nextStats.applied % 50 === 0 || input.reason === "final",
    shouldScheduleNextFrame: input.drain.shouldContinue,
    shouldInvalidateSession: input.reason === "final" && (Boolean(input.drain.telemetry.done) || finalDone),
    lastAppliedAtMs: applyFinishedAtMs,
    telemetry,
  };
}

function sessionDetailPhase(detail: SessionDetail) {
  return String(detail.currentPhase || detail.status || "").trim().toLowerCase();
}

function isFinalSessionDetailPhase(
  detail: SessionDetail,
  isBusyPhase: (phase: string) => boolean,
) {
  const phase = sessionDetailPhase(detail);
  return Boolean(phase && !isBusyPhase(phase));
}

function assistantDeltaApplyTelemetry(input: {
  streamSessionId: string;
  reason: SessionAssistantDeltaDrainReason;
  drain: SessionAssistantDeltaDrainResult;
  stats: SessionStreamApplyStats;
  appliedPayloadCount: number;
  pendingLayer: ActiveTurnLayerState | undefined;
  applyStartedAtMs: number;
  applyFinishedAtMs: number;
}) {
  const telemetryOldestReceivedAtMs = input.drain.telemetry.oldestReceivedAtMs ?? 0;
  const telemetryNewestReceivedAtMs = input.drain.telemetry.newestReceivedAtMs ?? telemetryOldestReceivedAtMs;
  const telemetryFrameScheduledAtMs = input.drain.telemetry.frameScheduledAtMs ?? 0;
  const itemCounts = canonicalItemCounts(
    input.drain.entries.flatMap((entry) => entry.payload.turnItems ?? []),
  );
  return {
    sessionId: input.streamSessionId,
    reason: input.reason,
    turnId: input.drain.telemetry.turnId ?? "",
    stage: input.drain.telemetry.stage ?? "",
    receivedCount: input.stats.received,
    appliedCount: input.stats.applied,
    droppedCount: input.stats.dropped,
    payloadLength: input.drain.telemetry.payloadLength ?? 0,
    contentDeltaLength: input.drain.telemetry.contentDeltaLength ?? 0,
    thoughtDeltaLength: input.drain.telemetry.thoughtDeltaLength ?? 0,
    pendingTextLength: activeTurnLayerTextLength(input.pendingLayer),
    batchSize: input.drain.telemetry.batchSize ?? input.appliedPayloadCount,
    done: input.drain.telemetry.done ?? false,
    turnRenderProtocol: input.drain.telemetry.turnRenderProtocol ?? "",
    ...itemCounts,
    drainMode: input.drain.mode,
    pendingBefore: input.drain.pendingBefore,
    pendingAfter: input.drain.pendingAfter,
    oldestQueuedAgeMs: Math.round(input.drain.oldestQueuedAgeMs),
    oldestReceivedAtMs: Math.round(telemetryOldestReceivedAtMs),
    newestReceivedAtMs: Math.round(telemetryNewestReceivedAtMs),
    frameScheduledAtMs: Math.round(telemetryFrameScheduledAtMs),
    applyStartedAtMs: Math.round(input.applyStartedAtMs),
    applyFinishedAtMs: Math.round(input.applyFinishedAtMs),
    receivedToApplyMs: Math.max(0, Math.round(input.applyStartedAtMs - telemetryOldestReceivedAtMs)),
    queuedForMs: Math.max(0, Math.round(input.applyStartedAtMs - telemetryNewestReceivedAtMs)),
    frameLagMs: telemetryFrameScheduledAtMs
      ? Math.max(0, Math.round(input.applyStartedAtMs - telemetryFrameScheduledAtMs))
      : 0,
    applyElapsedMs: Math.max(0, Math.round(input.applyFinishedAtMs - input.applyStartedAtMs)),
  };
}
