import type { SessionDetail, SessionTurnItem } from "../api/types";
import {
  activeTurnLayerTextLength,
  mergeAssistantDeltaIntoActiveTurnLayer,
  type ActiveTurnLayerState,
  type AssistantDeltaEvent,
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
  clearActiveLayerReason: "committed_detail" | "";
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
  /**
   * Optional projection continuity gate (chatStreamProjectionGate). When
   * provided, each drained payload passes through it before merge: stale
   * frames are dropped and gap-held frames stop the drain (the remaining
   * entries are counted as held and left to the watermark recovery).
   */
  assistantDeltaSeqGate?: (payload: AssistantDeltaEvent) =>
    | { action: "apply" }
    | { action: "drop-stale" }
    | { action: "hold-gap"; watermark: number; seq: number };
};

export type AppliedAssistantDeltaDrainDecision =
  | {
    applied: false;
    stats: SessionStreamApplyStats;
    appliedPayloadCount: 0;
    shouldLogApplied: false;
    shouldScheduleNextFrame: false;
    shouldInvalidateSession: false;
    hold?: AssistantDeltaDrainHoldInfo;
  }
  | {
    applied: true;
    nextCommittedLayer: ActiveTurnLayerState | undefined;
    shouldCommitRender: boolean;
    stats: SessionStreamApplyStats;
    appliedPayloadCount: number;
    finalDone: boolean;
    shouldLogApplied: boolean;
    shouldScheduleNextFrame: boolean;
    shouldInvalidateSession: boolean;
    lastAppliedAtMs: number;
    telemetry: Record<string, unknown>;
    hold?: AssistantDeltaDrainHoldInfo;
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

  const clearByCommittedDetail = Boolean(input.activeLayer && input.activeLayerSettled);
  const clearActiveLayer = clearByCommittedDetail;
  const clearActiveLayerReason = clearByCommittedDetail ? "committed_detail" : "";

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

export type AssistantDeltaDrainHoldInfo = {
  /** Ledger sequence of the first gap-held frame. */
  heldLedgerSeq: number;
  /** Watermark the recovery resubscribes from (lastAppliedSeq + 1). */
  watermark: number;
  /** Entries skipped by the hold (the held frame plus everything behind it). */
  heldCount: number;
};

export function planAppliedAssistantDeltaDrain(
  input: PlanAppliedAssistantDeltaDrainInput,
): AppliedAssistantDeltaDrainDecision {
  let pendingLayer = input.committedLayer;
  let appliedPayloadCount = 0;
  let finalDone = false;
  let holdInfo: AssistantDeltaDrainHoldInfo | null = null;
  const entries = input.drain.entries;
  for (let entryIndex = 0; entryIndex < entries.length; entryIndex += 1) {
    const entry = entries[entryIndex];
    if (input.assistantDeltaSeqGate) {
      const gateDecision = input.assistantDeltaSeqGate(entry.payload);
      if (gateDecision.action === "hold-gap") {
        // Continuity gate: the frame (and everything queued behind it) is held
        // instead of corrupting the projection; the watermark recovery brings
        // the authoritative state that closes the gap.
        holdInfo = {
          heldLedgerSeq: gateDecision.seq,
          watermark: gateDecision.watermark,
          heldCount: entries.length - entryIndex,
        };
        break;
      }
      if (gateDecision.action === "drop-stale") {
        continue;
      }
    }
    pendingLayer = mergeAssistantDeltaIntoActiveTurnLayer(pendingLayer, entry.payload);
    appliedPayloadCount += 1;
    finalDone = finalDone || entry.payload.done;
  }

  const currentStats = normalizeSessionStreamApplyStats(input.stats);
  const heldCount = holdInfo?.heldCount ?? 0;
  if (appliedPayloadCount === 0) {
    return {
      applied: false,
      stats: heldCount > 0
        ? { ...currentStats, dropped: currentStats.dropped + heldCount }
        : currentStats,
      appliedPayloadCount: 0,
      shouldLogApplied: false,
      shouldScheduleNextFrame: false,
      shouldInvalidateSession: false,
      ...(holdInfo ? { hold: holdInfo } : {}),
    };
  }

  const shouldCommitRender = !sameActiveTurnRenderState(input.committedLayer, pendingLayer);
  const nextStats = {
    ...currentStats,
    applied: currentStats.applied + (shouldCommitRender ? 1 : 0),
    dropped: currentStats.dropped
      + (shouldCommitRender ? heldCount : appliedPayloadCount + heldCount),
  };
  const applyFinishedAtMs = input.applyFinishedAtMs ?? input.nowMs?.() ?? input.applyStartedAtMs;
  const shouldLogApplied = input.reason === "final"
    || (shouldCommitRender
      ? nextStats.applied === 1 || nextStats.applied % 50 === 0
      : nextStats.dropped === 1 || nextStats.dropped % 50 === 0);
  // Building the telemetry body walks the whole pending layer (full text join +
  // cell projection); it is only consumed when a log entry is actually emitted.
  const telemetry = shouldLogApplied
    ? assistantDeltaApplyTelemetry({
      streamSessionId: input.streamSessionId,
      reason: input.reason,
      drain: input.drain,
      stats: nextStats,
      appliedPayloadCount,
      pendingLayer,
      shouldCommitRender,
      applyStartedAtMs: input.applyStartedAtMs,
      applyFinishedAtMs,
    })
    : {};

  return {
    applied: true,
    nextCommittedLayer: pendingLayer,
    shouldCommitRender,
    stats: nextStats,
    appliedPayloadCount,
    finalDone,
    shouldLogApplied,
    shouldScheduleNextFrame: input.drain.shouldContinue,
    shouldInvalidateSession: input.reason === "final" && (Boolean(input.drain.telemetry.done) || finalDone),
    lastAppliedAtMs: applyFinishedAtMs,
    telemetry,
    ...(holdInfo ? { hold: holdInfo } : {}),
  };
}

const activeTurnRenderSignatureCache = new WeakMap<ActiveTurnLayerState, string>();

function turnItemRenderFingerprint(item: SessionTurnItem) {
  return [
    item.type,
    item.itemId,
    item.status,
    item.terminal,
    item.revision,
    item.sequence,
    "text" in item ? item.text.length : 0,
    item.type === "tool_call" ? (item.output?.length ?? 0) : 0,
    item.summary?.length ?? 0,
    item.type === "retry" ? (item.reason?.length ?? 0) : 0,
  ].join(":");
}

/**
 * O(item count) fingerprint: text fields enter by length only. Streaming items
 * are append-revisioned (revision/sequence bumps on every change), so an equal
 * length with equal revision means the same replayed frame — skipping that
 * render commit matches the previous full-text JSON comparison semantics
 * without the O(total stream length) cost per drain.
 */
function activeTurnRenderSignature(layer: ActiveTurnLayerState) {
  const cached = activeTurnRenderSignatureCache.get(layer);
  if (cached !== undefined) {
    return cached;
  }
  const signature = [
    layer.sessionId,
    layer.turnId,
    layer.status,
    layer.processStage,
    layer.turnItems.map(turnItemRenderFingerprint).join("\u001e"),
  ].join("\u001f");
  activeTurnRenderSignatureCache.set(layer, signature);
  return signature;
}

function sameActiveTurnRenderState(
  previous: ActiveTurnLayerState | undefined,
  next: ActiveTurnLayerState | undefined,
) {
  if (previous === next) {
    return true;
  }
  if (!previous || !next) {
    return false;
  }
  return activeTurnRenderSignature(previous) === activeTurnRenderSignature(next);
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
  shouldCommitRender: boolean;
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
    renderCommitted: input.shouldCommitRender,
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
