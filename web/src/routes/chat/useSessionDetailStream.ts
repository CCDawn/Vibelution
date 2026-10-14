import { useCallback, useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../../app/browserTelemetry";
import { getPageInstanceId } from "../../app/pageInstance";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionStreamEvent, SessionTurnItem } from "../../api/types";
import {
  bindActiveTurnLayerToTurnId,
  isActiveTurnSettledByDetail,
  latestUserTurnId,
  reconcileActiveTurnLayerItemsWithMessages,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import {
  createSessionStreamAppendReassembler,
  routeSessionStreamEvent,
  sessionStreamProtocolTelemetryFields,
  type SessionStreamAppendGap,
  type SessionStreamProtocolTrace,
} from "../chatSessionStreamProtocol";
import {
  normalizeSessionStreamApplyStats,
  planAppliedAssistantDeltaDrain,
  planAppliedSessionDetail,
  planQueuedSessionDetail,
  type SessionStreamApplyStats,
} from "../chatStreamApplyController";
import { createSessionAssistantDeltaScheduler } from "../sessionAssistantDeltaScheduler";
import { chatStreamPerformanceNowMs, isBusyPhase } from "./chatCodingRouteViewModel";
import { supersededEditDelta } from "./chatEditResubmitState";
import {
  createAssistantDeltaSeqGate,
  createSessionStreamRecoveryController,
  SESSION_STREAM_RECOVERY_MAX_ATTEMPTS,
} from "../chatStreamProjectionGate";
import { mergeSessionDetailMessageWindowWithOutcome } from "../chatSessionState";
import {
  SESSION_STREAM_ERROR_REFRESH_MIN_INTERVAL_MS,
  SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
  SESSION_STREAM_ROUTE_SWITCH_GRACE_MS,
  type SessionStreamDecisionSnapshot,
} from "./chatSessionStreamConnect";
import {
  createSessionEventStream as createDefaultSessionEventStream,
  type SessionEventStream,
} from "./sessionEventStream";
import {
  acquireSessionStream,
  releaseSessionStream,
  SESSION_STREAM_WARM_MS,
} from "./sessionStreamWarmRegistry";

type DesktopConversationNotifier = {
  handleSessionDetail: (
    detail: SessionDetail,
    options: { sessionTitle: string; viewedSessionId?: string },
  ) => void;
  handleAssistantDelta: (
    payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
    options: { sessionTitle: string; viewedSessionId?: string },
  ) => void;
};

export function shouldDropSupersededEditDelta(
  protection: SessionDetail["editResubmitProtection"],
  turnId: string | undefined,
  ledgerSeq?: number,
): boolean {
  return supersededEditDelta(protection, turnId, ledgerSeq);
}

function normalizedLedgerSeq(value: unknown): number {
  const sequence = Number(value ?? 0);
  return Number.isFinite(sequence) && sequence > 0 ? sequence : 0;
}

function normalizedTurnId(value: unknown): string {
  const turnId = String(value ?? "").trim();
  return turnId.startsWith("live:") ? turnId.slice("live:".length) : turnId;
}

function sessionTurnIdForMessage(message: SessionDetail["messages"][number]): string {
  return normalizedTurnId(message.metadata?.turnId || message.metadata?.turn_id);
}

function sessionTurnItemsForDetail(detail: SessionDetail, turnId: string): SessionTurnItem[] {
  if (!turnId) {
    return [];
  }
  return (detail.messages ?? []).flatMap((message) => (
    message.role === "assistant"
      && message.metadata?.kind !== "session_active_turn_layer"
      && sessionTurnIdForMessage(message) === turnId
      ? message.turnItems ?? []
      : []
  ));
}

/** Why a guarded stream was hard-closed by its owner (telemetry evidence). */
export type SessionStreamCloseReason = "grace_timeout" | "manual_reconnect" | "append_gap";

export type UseSessionDetailStreamOptions = {
  activeSessionId: string | null | undefined;
  sessionStreamShouldConnect: boolean;
  queryClient: QueryClient;
  syncSessionDetail: (detail: SessionDetail) => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  activeTurnLayersBySessionRef: MutableRefObject<Record<string, ActiveTurnLayerState>>;
  lastAssistantDeltaAppliedAtRef: MutableRefObject<Record<string, number>>;
  /**
   * Epoch-ms stamp of the last APPLIED stream event per session (applied delta
   * frame or applied detail reconcile). This is the no-output stall baseline:
   * any applied frame counts as activity, body text or not — received-but-held
   * frames must never reset it. Kept separate from
   * `lastAssistantDeltaAppliedAtRef`, whose performance-clock values feed the
   * applyToPaintMs telemetry only.
   */
  lastStreamActivityAppliedAtRef: MutableRefObject<Record<string, number>>;
  sessionStreamDecisionSnapshotRef: MutableRefObject<SessionStreamDecisionSnapshot>;
  desktopConversationNotifierRef: MutableRefObject<DesktopConversationNotifier>;
  createSessionEventStream?: (sessionId: string) => SessionEventStream;
  /** Live title for desktop notifications (detail title or summary title). */
  sessionTitleForNotifications: string;
  viewedSessionId?: string;
};

/**
 * Sole owner of the direct-session guarded event stream, through the module
 * level keep-warm registry (sessionStreamWarmRegistry): unmount parks the
 * stream instead of closing it. Do not open a second
 * /api/sessions/:id/events connection elsewhere.
 */
export function useSessionDetailStream({
  activeSessionId,
  sessionStreamShouldConnect,
  queryClient,
  syncSessionDetail,
  setActiveTurnLayersBySession,
  activeTurnLayersBySessionRef,
  lastAssistantDeltaAppliedAtRef,
  lastStreamActivityAppliedAtRef,
  sessionStreamDecisionSnapshotRef,
  desktopConversationNotifierRef,
  createSessionEventStream = createDefaultSessionEventStream,
  sessionTitleForNotifications,
  viewedSessionId,
}: UseSessionDetailStreamOptions): {
  sessionStreamConnected: boolean;
  streamDisconnectedSinceMs: number | null;
  /** Manual "reconnect now" affordance for the active-turn disconnect advisory. */
  reconnectSessionStream: () => void;
} {
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  // Sticky start of the current reconnect loop: set on the first transport
  // error, cleared by the next successful open or a fresh stream effect. The
  // active-turn status note reads it to show "disconnected · Ns"; it is not
  // set for route-settling teardowns, which are not real drops.
  const [streamDisconnectedSinceMs, setStreamDisconnectedSinceMs] = useState<number | null>(null);
  const [streamReconnectTick, setStreamReconnectTick] = useState(0);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamErrorRefreshAtRef = useRef<Record<string, number>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamApplyStatsRef = useRef<Record<string, SessionStreamApplyStats>>({});
  const sessionStreamStopFrozenLoggedRef = useRef<Record<string, boolean>>({});
  const sessionTitleForNotificationsRef = useRef(sessionTitleForNotifications);
  sessionTitleForNotificationsRef.current = sessionTitleForNotifications;
  const viewedSessionIdRef = useRef(viewedSessionId || activeSessionId || "");
  viewedSessionIdRef.current = viewedSessionId || activeSessionId || "";

  // Perf root cause: sessionStreamShouldConnect flaps while the route settles.
  // Keeping it out of the stream effect's dependency list stops close/reopen
  // storms; a grace timer closes the stream only after the decision stays false.
  const shouldConnectRef = useRef(sessionStreamShouldConnect);
  const prevShouldConnectRef = useRef<boolean | null>(null);
  const graceCloseTimerRef = useRef<number | null>(null);
  const graceClosedSessionRef = useRef(false);
  const activeStreamRef = useRef<{ stream: SessionEventStream; sessionId: string } | null>(null);
  const forceCloseStreamRef = useRef<((reason?: SessionStreamCloseReason) => void) | null>(null);

  useEffect(() => {
    const prev = prevShouldConnectRef.current;
    prevShouldConnectRef.current = sessionStreamShouldConnect;
    shouldConnectRef.current = sessionStreamShouldConnect;
    if (sessionStreamShouldConnect) {
      if (graceCloseTimerRef.current !== null) {
        window.clearTimeout(graceCloseTimerRef.current);
        graceCloseTimerRef.current = null;
      }
      if (prev === false && (!activeStreamRef.current || graceClosedSessionRef.current)) {
        graceClosedSessionRef.current = false;
        setStreamReconnectTick((tick) => tick + 1);
      }
      return;
    }
    if (graceCloseTimerRef.current !== null) {
      return;
    }
    graceCloseTimerRef.current = window.setTimeout(() => {
      graceCloseTimerRef.current = null;
      if (shouldConnectRef.current || !activeStreamRef.current) {
        return;
      }
      forceCloseStreamRef.current?.();
    }, SESSION_STREAM_ROUTE_SWITCH_GRACE_MS);
  }, [sessionStreamShouldConnect]);

  useEffect(() => {
    const shouldConnect = sessionStreamDecisionSnapshotRef.current.shouldConnect;
    // A new stream effect owns the advisory clock; stale disconnect timing
    // from a previous session must not leak into the next one.
    setStreamDisconnectedSinceMs(null);
    if (!shouldConnect) {
      const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
      setSessionStreamConnected(false);
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.skipped",
        message: "Session detail stream connection was skipped.",
        level: "info",
        fields: {
          sessionId: decisionSnapshot.sessionId,
          shouldConnect: decisionSnapshot.shouldConnect,
          pageVisible: decisionSnapshot.pageVisible,
          chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
          chatPollingVisible: decisionSnapshot.chatPollingVisible,
          directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
          routeTargetMatches: decisionSnapshot.routeTargetMatches,
          routeSettling: decisionSnapshot.routeSettling,
          routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
          visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
          guardedFetchStreamAvailable: typeof fetch !== "undefined",
          pageInstanceId: getPageInstanceId(),
          ...collectBrowserPageSnapshot(),
        },
      });
      return;
    }

    let disposed = false;
    const markStreamConnected = () => {
      setSessionStreamConnected(true);
      setStreamDisconnectedSinceMs(null);
    };
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId) {
      setSessionStreamConnected(false);
      return;
    }
    const initialCachedDetail = queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId));
    let authoritativeLedgerSeq = normalizedLedgerSeq(initialCachedDetail?.ledgerSeq);
    let authoritativePhase = String(initialCachedDetail?.currentPhase || initialCachedDetail?.status || "")
      .trim()
      .toLowerCase();
    let authoritativeTurnId = normalizedTurnId(initialCachedDetail?.activeTurnId)
      || (isBusyPhase(authoritativePhase) ? latestUserTurnId(initialCachedDetail) : "");
    const noteAuthorityState = (snapshot: {
      ledgerSeq?: number;
      activeTurnId?: string;
      currentPhase?: string;
      status?: string;
    }) => {
      const incomingLedgerSeq = normalizedLedgerSeq(snapshot.ledgerSeq);
      if (authoritativeLedgerSeq > 0 && (incomingLedgerSeq === 0 || incomingLedgerSeq < authoritativeLedgerSeq)) {
        return;
      }
      authoritativeLedgerSeq = Math.max(authoritativeLedgerSeq, incomingLedgerSeq);
      const phase = String(snapshot.currentPhase || snapshot.status || "").trim().toLowerCase();
      if (snapshot.activeTurnId !== undefined) {
        authoritativeTurnId = normalizedTurnId(snapshot.activeTurnId);
      } else if (phase && isBusyPhase(phase)) {
        authoritativeTurnId = latestUserTurnId(snapshot as SessionDetail) || authoritativeTurnId;
      } else if (phase && !isBusyPhase(phase)) {
        authoritativeTurnId = "";
      }
      if (phase) {
        authoritativePhase = phase;
      }
    };
    const currentAuthorityState = () => {
      const cached = queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId));
      if (cached && normalizedLedgerSeq(cached.ledgerSeq) >= authoritativeLedgerSeq) {
        noteAuthorityState(cached);
      }
      return {
        ledgerSeq: authoritativeLedgerSeq,
        turnId: authoritativeTurnId,
        phase: authoritativePhase,
      };
    };
    const shouldDropDeltaAgainstAuthority = (
      payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
    ) => {
      const authority = currentAuthorityState();
      const incomingLedgerSeq = normalizedLedgerSeq(payload.ledgerSeq);
      const authorityIsTerminal = Boolean(authority.phase && !isBusyPhase(authority.phase));
      if (
        authorityIsTerminal
        && authority.turnId
        && payload.turnId === authority.turnId
      ) {
        return true;
      }
      if (
        authorityIsTerminal
        && !authority.turnId
        && (!incomingLedgerSeq || !authority.ledgerSeq || incomingLedgerSeq <= authority.ledgerSeq)
      ) {
        return true;
      }
      if (
        authority.turnId
        && payload.turnId !== authority.turnId
        && (!incomingLedgerSeq || !authority.ledgerSeq || incomingLedgerSeq <= authority.ledgerSeq)
      ) {
        return true;
      }
      if (!incomingLedgerSeq || !authority.ledgerSeq) {
        return false;
      }
      if (incomingLedgerSeq < authority.ledgerSeq) {
        return true;
      }
      if (incomingLedgerSeq > authority.ledgerSeq) {
        return false;
      }
      if (authority.turnId && payload.turnId !== authority.turnId) {
        return true;
      }
      return !authority.turnId && Boolean(authority.phase && !isBusyPhase(authority.phase));
    };
    let pendingDetail: SessionDetail | null = null;
    let pendingDetailTrace: SessionStreamProtocolTrace | null = null;
    let applyTimer: number | null = null;
    let lastAppliedAt = 0;
    let committedAssistantDeltaLayer: ActiveTurnLayerState | undefined = activeTurnLayersBySessionRef.current[streamSessionId];
    let observedEditSubmissionId = "";
    let appendGapLogged = false;
    let journalReplayLogged = false;
    const sessionStreamAppendReassembler = createSessionStreamAppendReassembler();
    const initialDetailPhase = String(initialCachedDetail?.currentPhase || initialCachedDetail?.status || "")
      .trim()
      .toLowerCase();
    const initialTurnId = String(initialCachedDetail?.activeTurnId || "").trim()
      || (isBusyPhase(initialDetailPhase) ? latestUserTurnId(initialCachedDetail) : "");
    const initialLayer = committedAssistantDeltaLayer;
    const initialTurnItems = initialLayer?.turnId === initialTurnId
      && initialLayer.ledgerSeq >= normalizedLedgerSeq(initialCachedDetail?.ledgerSeq)
      ? initialLayer.turnItems
      : initialCachedDetail
        ? sessionTurnItemsForDetail(initialCachedDetail, initialTurnId)
        : [];
    sessionStreamAppendReassembler.rebase(streamSessionId, initialTurnId, initialTurnItems);
    const assistantDeltaScheduler = createSessionAssistantDeltaScheduler({
      nowMs: chatStreamPerformanceNowMs,
    });
    let assistantDeltaApplyFrame: number | null = null;
    let frameScheduledAtMs = 0;
    let rejectedSessionStreamRouteLogged = false;
    const decisionSnapshot = sessionStreamDecisionSnapshotRef.current;
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.effect_started",
      message: "Session detail stream effect started.",
      level: "info",
      fields: {
        sessionId: streamSessionId,
        shouldConnect: decisionSnapshot.shouldConnect,
        pageVisible: decisionSnapshot.pageVisible,
        chatStartupWarmupActive: decisionSnapshot.chatStartupWarmupActive,
        chatPollingVisible: decisionSnapshot.chatPollingVisible,
        directSessionBackgroundSyncActive: decisionSnapshot.directSessionBackgroundSyncActive,
        routeTargetMatches: decisionSnapshot.routeTargetMatches,
        routeSettling: decisionSnapshot.routeSettling,
        routeSwitchGraceActive: decisionSnapshot.routeSwitchGraceActive,
        routeSwitchGraceMsRemaining: decisionSnapshot.routeSwitchGraceMsRemaining,
        visibilityState: typeof document === "undefined" ? "unknown" : document.visibilityState,
        pageInstanceId: getPageInstanceId(),
        ...collectBrowserPageSnapshot(),
      },
    });
    // Keep-warm acquire (pattern: zai-org/ZCode sessionDataLayer, Apache-2.0):
    // remounting the same session within the warm window reuses the parked live
    // connection instead of paying a cold reconnect + resync.
    const acquired = acquireSessionStream(streamSessionId, createSessionEventStream);
    const stream = acquired.stream;
    const reacquiredWarm = acquired.reusedWarm;
    const parkedLedgerSeq = acquired.parkedLedgerSeq;
    activeStreamRef.current = { stream, sessionId: streamSessionId };
    let closeTelemetryFired = false;

    const sessionStopIntentActive = () =>
      Boolean(queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId))?.stopRequested);

    const syncEditResubmitGuard = () => {
      const protection = queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId))?.editResubmitProtection;
      const submissionId = String(protection?.clientSubmissionId || "").trim();
      if (submissionId && submissionId !== observedEditSubmissionId) {
        // A new edit replaces the local delta accumulator as well as the
        // transcript tail; queued deltas from the superseded turn must not be
        // appended to the new optimistic layer.
        assistantDeltaScheduler.cancel();
        committedAssistantDeltaLayer = undefined;
        observedEditSubmissionId = submissionId;
      } else if (!submissionId) {
        observedEditSubmissionId = "";
      }
      return protection;
    };

    const logStopFrozenDeltas = (droppedCount: number) => {
      if (sessionStreamStopFrozenLoggedRef.current[streamSessionId]) {
        return;
      }
      sessionStreamStopFrozenLoggedRef.current[streamSessionId] = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.stop_intent_frozen_delta",
        message: "Session assistant deltas were dropped while a stop intent is active.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          droppedCount,
        },
      });
    };

    // Epoch-ms activity stamp for the no-output stall advisory. Written only
    // at the two "applied" funnels below: the projection gate (or apply
    // decision) must have accepted the event — receiving a frame is not
    // activity. Date.now() on purpose: the consumer ticks with wall-clock.
    const stampStreamActivity = () => {
      lastStreamActivityAppliedAtRef.current = {
        ...lastStreamActivityAppliedAtRef.current,
        [streamSessionId]: Date.now(),
      };
    };

    const forceCloseStream = (reason: SessionStreamCloseReason = "grace_timeout") => {
      if (closeTelemetryFired || disposed) {
        return;
      }
      closeTelemetryFired = true;
      activeStreamRef.current = null;
      applyPendingAssistantDeltas("close");
      applyPendingDetail("close");
      setSessionStreamConnected(false);
      stream.close();
      graceClosedSessionRef.current = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.closed",
        message: "Session detail stream closed.",
        fields: {
          sessionId: streamSessionId,
          readyState: stream.readyState,
          reason,
        },
      });
      setStreamReconnectTick((tick) => tick + 1);
    };
    forceCloseStreamRef.current = forceCloseStream;

    // Projection invariants (pattern: zai-org/ZCode conversationProjectionStore,
    // Apache-2.0): seq continuity gate before delta application + single-flight
    // watermark recovery. The authoritative refetch after stream errors below
    // stays as the coarse fallback path.
    const sessionProjectionGate = createAssistantDeltaSeqGate();
    const sessionStreamRecovery = createSessionStreamRecoveryController({
      requestRecovery: ({ attempt }) => {
        if (disposed) {
          return;
        }
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
        // The reconnect re-baselines the gate through the stream open handler;
        // once the backoff ladder is exhausted only the authoritative refetch
        // keeps running so a flapping transport cannot loop reconnects.
        if (attempt <= SESSION_STREAM_RECOVERY_MAX_ATTEMPTS) {
          forceCloseStream();
        }
      },
    });

    if (reacquiredWarm) {
      // The stream stayed open while this session was parked, so it may have
      // reconnected or advanced without a mounted owner. Re-baseline the
      // projection gates (the next frame applies like after a fresh open).
      // A fresh lightweight select handoff is not a hydrated transcript. A
      // remount can skip GET on freshness and never receive another initial
      // frame from this warm stream, so unread bodies also need a readback.
      sessionProjectionGate.noteStreamReopened();
      sessionStreamRecovery.noteStreamReopened();
      const cachedLedgerSeq = normalizedLedgerSeq(initialCachedDetail?.ledgerSeq);
      const transcriptUnhydrated = !initialCachedDetail
        || initialCachedDetail.id !== streamSessionId
        || Boolean(initialCachedDetail.provisionalTranscript);
      if (transcriptUnhydrated || parkedLedgerSeq > cachedLedgerSeq) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId), exact: true });
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.warm_readback_requested",
          message: "Warm session stream requested a canonical detail readback.",
          fields: {
            sessionId: streamSessionId,
            reason: transcriptUnhydrated ? "transcript_unhydrated" : "ledger_advanced",
            cachedLedgerSeq,
            parkedLedgerSeq,
          },
        });
      }
      if (stream.readyState === 1) {
        markStreamConnected();
      }
    }

    function logRejectedSessionStreamRoute(trace: SessionStreamProtocolTrace, message: string) {
      if (trace.rejectReason === "parse_error") {
        if (!sessionStreamPayloadErrorLoggedRef.current[streamSessionId]) {
          sessionStreamPayloadErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.bad_payload",
            message,
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              payloadLength: trace.payloadLength,
              ...sessionStreamProtocolTelemetryFields(trace),
            },
          });
        }
        return;
      }
      if (rejectedSessionStreamRouteLogged) {
        return;
      }
      rejectedSessionStreamRouteLogged = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.event_rejected",
        message: "Session stream event was rejected by the protocol router.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          ...sessionStreamProtocolTelemetryFields(trace),
        },
      });
    }

    function applyPendingDetail(reason: "timer" | "close" | "final") {
      if (!pendingDetail || disposed) {
        return;
      }
      const incomingDetail = pendingDetail;
      const mergeOutcome = mergeSessionDetailMessageWindowWithOutcome(
        queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId)), pendingDetail);
      const trace = pendingDetailTrace;
      pendingDetail = null;
      pendingDetailTrace = null;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      if (!mergeOutcome.authorityAccepted) {
        const stats = normalizeSessionStreamApplyStats(sessionStreamApplyStatsRef.current[streamSessionId]);
        if (mergeOutcome.historyMerged) {
          stats.applied += 1;
          // Keep older history paging useful while leaving all live control
          // decisions attached to the accepted cache generation.
          syncSessionDetail(incomingDetail);
        } else {
          stats.dropped += 1;
        }
        sessionStreamApplyStatsRef.current[streamSessionId] = stats;
        return;
      }
      syncSessionDetail(mergeOutcome.detail);
      const detail = queryClient.getQueryData<SessionDetail>(queryKeys.session(streamSessionId))
        ?? mergeOutcome.detail;
      noteAuthorityState(detail);
      const authoritativeLedgerSeq = normalizedLedgerSeq(detail.ledgerSeq);
      sessionProjectionGate.noteAuthoritative(authoritativeLedgerSeq);
      if (authoritativeLedgerSeq > 0) {
        sessionStreamRecovery.noteAuthoritative(authoritativeLedgerSeq);
      }
      lastAppliedAt = Date.now();
      const activeLayer = activeTurnLayersBySessionRef.current[streamSessionId];
      const decision = planAppliedSessionDetail({
        streamSessionId,
        reason,
        detail,
        trace,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        activeLayer,
        activeLayerSettled: isActiveTurnSettledByDetail(activeLayer, detail),
        isBusyPhase,
      });
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      if (decision.shouldLogApplied) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_applied",
          message: "Session detail stream snapshot was applied to the UI cache.",
          level: "info",
          fields: decision.telemetry,
        });
      }
      desktopConversationNotifierRef.current.handleSessionDetail(detail, {
        sessionTitle: detail.title || detail.agentDisplayName || detail.id,
        viewedSessionId: viewedSessionIdRef.current,
      });
      if (decision.clearActiveLayer) {
        committedAssistantDeltaLayer = undefined;
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, undefined)
        );
        sessionProjectionGate.noteTurnBoundary();
        sessionStreamAppendReassembler.rebase(streamSessionId, "", []);
        return;
      }
      // Authoritative snapshot application: rewrites the projection from the
      // authority, which re-baselines the continuity gate and retires a
      // pending watermark recovery episode.
      // Per-item overlay reconciliation (projection invariant c): overlay turn
      // items the canonical transcript already commits are dropped at item
      // granularity; whole-turn settlement above stays the coarse path.
      const detailPhase = String(detail.currentPhase || detail.status || "").trim().toLowerCase();
      const authoritativeTurnId = normalizedTurnId(detail.activeTurnId)
        || (isBusyPhase(detailPhase) ? latestUserTurnId(detail) : "");
      let rebasedLayer = activeLayer;
      if (activeLayer && authoritativeTurnId && activeLayer.turnId !== authoritativeTurnId) {
        const boundLayer = bindActiveTurnLayerToTurnId(activeLayer, authoritativeTurnId);
        if (boundLayer) {
          rebasedLayer = {
            ...boundLayer,
            turnItems: sessionTurnItemsForDetail(detail, authoritativeTurnId),
            ledgerSeq: Math.max(boundLayer.ledgerSeq, normalizedLedgerSeq(detail.ledgerSeq)),
          };
        }
      }
      const reconciledLayer = rebasedLayer
        ? reconcileActiveTurnLayerItemsWithMessages(rebasedLayer, detail.messages)
        : undefined;
      if (reconciledLayer !== activeLayer) {
        if (
          activeLayer
          && reconciledLayer
          && reconciledLayer.turnId === activeLayer.turnId
          && reconciledLayer.turnItems.length < activeLayer.turnItems.length
        ) {
          // Reconcile actually advanced the overlay: applied activity too.
          stampStreamActivity();
        }
        committedAssistantDeltaLayer = reconciledLayer;
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, reconciledLayer)
        );
      } else {
        committedAssistantDeltaLayer = reconciledLayer;
      }
      const baselineTurnItems = reconciledLayer?.turnId === authoritativeTurnId
        ? reconciledLayer.turnItems
        : sessionTurnItemsForDetail(detail, authoritativeTurnId);
      sessionStreamAppendReassembler.rebase(streamSessionId, authoritativeTurnId, baselineTurnItems);
    }

    function queueSessionDetail(detail: SessionDetail, trace: SessionStreamProtocolTrace) {
      const decision = planQueuedSessionDetail({
        detail,
        trace,
        pendingDetail,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        lastAppliedAtMs: lastAppliedAt,
        nowMs: Date.now(),
        minApplyIntervalMs: SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
        isBusyPhase,
      });
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      pendingDetail = decision.pendingDetail;
      pendingDetailTrace = decision.pendingDetailTrace;
      if (decision.action === "apply_now") {
        applyPendingDetail(decision.applyReason ?? "final");
        return;
      }
      if (!applyTimer) {
        applyTimer = window.setTimeout(() => {
          applyTimer = null;
          applyPendingDetail("timer");
        }, decision.delayMs);
      }
      if (decision.shouldLogQueued) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.snapshot_queued",
          message: "Session detail stream snapshot was queued before UI cache apply.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            ...decision.telemetry,
          },
        });
      }
    }

    function applyPendingAssistantDeltas(reason: "frame" | "close" | "final") {
      syncEditResubmitGuard();
      if (assistantDeltaScheduler.pendingCount === 0 || disposed) {
        return;
      }
      if (sessionStopIntentActive()) {
        if (assistantDeltaApplyFrame !== null) {
          window.cancelAnimationFrame(assistantDeltaApplyFrame);
          assistantDeltaApplyFrame = null;
        }
        const frozenCount = assistantDeltaScheduler.pendingCount;
        assistantDeltaScheduler.cancel();
        const frozenStats = normalizeSessionStreamApplyStats(
          sessionStreamApplyStatsRef.current[streamSessionId],
        );
        frozenStats.dropped += frozenCount;
        sessionStreamApplyStatsRef.current[streamSessionId] = frozenStats;
        logStopFrozenDeltas(frozenCount);
        return;
      }
      const applyStartedAtMs = chatStreamPerformanceNowMs();
      if (assistantDeltaApplyFrame !== null) {
        window.cancelAnimationFrame(assistantDeltaApplyFrame);
        assistantDeltaApplyFrame = null;
      }
      const scheduledAtMs = frameScheduledAtMs;
      frameScheduledAtMs = 0;
      const drain = assistantDeltaScheduler.drain(reason, { frameScheduledAtMs: scheduledAtMs });
      const decision = planAppliedAssistantDeltaDrain({
        streamSessionId,
        reason,
        drain,
        committedLayer: committedAssistantDeltaLayer,
        stats: sessionStreamApplyStatsRef.current[streamSessionId],
        applyStartedAtMs,
        nowMs: chatStreamPerformanceNowMs,
        assistantDeltaSeqGate: (payload) => shouldDropDeltaAgainstAuthority(payload)
          ? { action: "drop-stale" }
          : sessionProjectionGate.decide(payload),
      });
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
      const drainHold = decision.hold;
      if (drainHold) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_gap_held",
          message: "Session assistant delta frame was held by the projection continuity gate.",
          level: "warning",
          fields: {
            sessionId: streamSessionId,
            heldDeltaSeq: drainHold.heldDeltaSeq,
            watermark: drainHold.watermark,
            heldCount: drainHold.heldCount,
          },
        });
        sessionStreamRecovery.request(drainHold.watermark);
      }
      if (!decision.applied) {
        if (decision.shouldScheduleNextFrame && !disposed) {
          scheduleAssistantDeltaFrame();
        }
        return;
      }
      // Any applied frame is stream activity, body delta or not (thinking /
      // tool turnItems ride assistant_delta too); held frames never reach here.
      // Written regardless of shouldCommitRender: a silent re-apply still
      // proves the stream is alive.
      stampStreamActivity();
      committedAssistantDeltaLayer = decision.nextCommittedLayer;
      if (decision.shouldCommitRender) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, decision.nextCommittedLayer)
        );
      }
      if (decision.shouldCommitRender) {
        lastAssistantDeltaAppliedAtRef.current = {
          ...lastAssistantDeltaAppliedAtRef.current,
          [streamSessionId]: decision.lastAppliedAtMs,
        };
      }
      if (decision.shouldLogApplied) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_applied",
          message: "Session assistant delta stream was applied to the active turn layer.",
          level: "info",
          fields: decision.telemetry,
        });
      }
      for (const payload of decision.appliedPayloads) {
        desktopConversationNotifierRef.current.handleAssistantDelta(payload, {
          sessionTitle: sessionTitleForNotificationsRef.current || streamSessionId,
          viewedSessionId: viewedSessionIdRef.current,
        });
      }
      if (decision.shouldScheduleNextFrame && !disposed) {
        scheduleAssistantDeltaFrame();
      }
      if (decision.shouldInvalidateSession) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
      }
    }

    function scheduleAssistantDeltaFrame() {
      if (assistantDeltaApplyFrame !== null || disposed) {
        return;
      }
      frameScheduledAtMs = chatStreamPerformanceNowMs();
      assistantDeltaApplyFrame = window.requestAnimationFrame(() => {
        assistantDeltaApplyFrame = null;
        applyPendingAssistantDeltas("frame");
      });
    }

    function queueAssistantDelta(
      payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
      trace: SessionStreamProtocolTrace,
    ) {
      const stats = sessionStreamApplyStatsRef.current[streamSessionId] ?? { received: 0, applied: 0, dropped: 0 };
      stats.received += 1;
      sessionStreamApplyStatsRef.current[streamSessionId] = stats;
      const editProtection = syncEditResubmitGuard();
      if (shouldDropSupersededEditDelta(editProtection, payload.turnId, payload.ledgerSeq)) {
        stats.dropped += 1;
        return;
      }
      if (shouldDropDeltaAgainstAuthority(payload)) {
        stats.dropped += 1;
        return;
      }
      if (sessionStopIntentActive()) {
        stats.dropped += 1;
        logStopFrozenDeltas(1);
        return;
      }
      sessionStreamStopFrozenLoggedRef.current[streamSessionId] = false;
      const expansion = sessionStreamAppendReassembler.expand(payload);
      if (expansion.gaps.length) {
        stats.dropped += 1;
        logAppendGaps(expansion.gaps, trace);
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
        forceCloseStream("append_gap");
        return;
      }
      const expandedPayload = expansion.payload;
      const queued = assistantDeltaScheduler.enqueue(expandedPayload, trace.payloadLength, trace);
      if (payload.done) {
        applyPendingAssistantDeltas("final");
        return;
      }
      scheduleAssistantDeltaFrame();
      if (stats.received === 1 || stats.received % 50 === 0) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.assistant_delta_frame_scheduled",
          message: "Session assistant delta stream was scheduled for the next browser frame.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
            turnId: expandedPayload.turnId,
            stage: expandedPayload.stage,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            payloadLength: trace.payloadLength,
            contentDeltaLength: queued.contentDeltaLength,
            thoughtDeltaLength: queued.thoughtDeltaLength,
            pendingTextLength: 0,
            batchSize: queued.pendingCount,
            done: expandedPayload.done,
            receivedAtMs: Math.round(queued.receivedAtMs),
            frameScheduledAtMs: Math.round(frameScheduledAtMs),
            queuedForMs: Math.max(0, Math.round(frameScheduledAtMs - queued.receivedAtMs)),
            ...sessionStreamProtocolTelemetryFields(trace),
          },
        });
      }
    }

    stream.onopen = () => {
      if (!disposed) {
        markStreamConnected();
        sessionStreamErrorLoggedRef.current[streamSessionId] = false;
        // A stream (re)open re-baselines the continuity gate: the first frame
        // after the server resumes applies even when the ledger jumped during
        // the outage, and any pending watermark recovery episode retires.
        sessionProjectionGate.noteStreamReopened();
        sessionStreamRecovery.noteStreamReopened();
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.opened",
          message: "Session detail stream opened.",
          level: "info",
          fields: {
            sessionId: streamSessionId,
          },
        });
      }
    };

    stream.onerror = () => {
      if (!disposed) {
        setSessionStreamConnected(false);
        // onerror fires on every failed reconnect attempt; keep the first
        // timestamp so the duration counter measures the whole outage.
        setStreamDisconnectedSinceMs((current) => current ?? Date.now());
        const pendingAssistantDeltaCount = assistantDeltaScheduler.pendingCount;
        applyPendingAssistantDeltas("close");
        // The stream reports an error on every reconnect attempt while it keeps
        // failing. Each authoritative refetch rewrites the session cache and
        // notifies its subscribers, so refreshing once per error storms React
        // Query (and the renders it triggers). One refresh per window still
        // recovers whatever the broken stream missed.
        const errorAtMs = Date.now();
        const lastErrorRefreshAtMs = sessionStreamErrorRefreshAtRef.current[streamSessionId] ?? 0;
        const shouldRefreshAuthoritativeDetail =
          errorAtMs - lastErrorRefreshAtMs >= SESSION_STREAM_ERROR_REFRESH_MIN_INTERVAL_MS;
        if (shouldRefreshAuthoritativeDetail) {
          sessionStreamErrorRefreshAtRef.current[streamSessionId] = errorAtMs;
          void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
        }
        if (!sessionStreamErrorLoggedRef.current[streamSessionId]) {
          sessionStreamErrorLoggedRef.current[streamSessionId] = true;
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.error",
            message: "Session detail stream reported an error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
            },
          });
          postBrowserTelemetry({
            phase: "session_stream",
            eventCode: "browser.session_stream.authoritative_refresh_requested",
            message: "Authoritative session detail refresh was requested after a stream error.",
            level: "warning",
            fields: {
              sessionId: streamSessionId,
              readyState: stream.readyState,
              pendingAssistantDeltaCount,
              refreshedAuthoritativeDetail: shouldRefreshAuthoritativeDetail,
            },
          });
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      if (disposed) {
        return;
      }
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_detail",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session detail stream payload could not be parsed.");
        return;
      }
      markStreamConnected();
      queueSessionDetail(routed.payload.detail, routed.trace);
    }

    function handleSessionInitial(event: MessageEvent<string>) {
      if (disposed) {
        return;
      }
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_initial",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session initial stream payload could not be parsed.");
        return;
      }
      markStreamConnected();
      // Re-baseline continuity bookkeeping on each (re)connect. This journal
      // watermark may trail the latest commit until the detail readback below;
      // it is informational for the delta gate so new live frames can apply.
      const initialLedgerSeq = Number(routed.payload.ledgerSeq ?? 0);
      noteAuthorityState({
        ledgerSeq: routed.payload.ledgerSeq,
        activeTurnId: routed.payload.activeTurnId,
        currentPhase: routed.payload.currentPhase || (routed.payload.running ? "running" : ""),
      });
      if (Number.isFinite(initialLedgerSeq) && initialLedgerSeq > 0) {
        sessionProjectionGate.noteAuthoritative(initialLedgerSeq);
        sessionStreamRecovery.noteAuthoritative(initialLedgerSeq);
      }
      // The server captures the light bootstrap before registering this
      // subscriber. A turn can settle in that gap without emitting any frame
      // to us. Read the canonical body after receiving the initial frame,
      // when the subscription is live; an open stream disables detail polling.
      const sessionQuery = { queryKey: queryKeys.session(streamSessionId), exact: true };
      // Invalidation alone can reuse an in-flight first fetch (no cached data
      // yet). Cancel it first so the readback starts after the subscription.
      void queryClient.cancelQueries(sessionQuery).then(() => {
        if (!disposed) void queryClient.invalidateQueries(sessionQuery);
      });
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.initial_received",
        message: "Session stream lightweight initial state was received.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          payloadLength: routed.trace.payloadLength,
          ledgerSeq: routed.payload.ledgerSeq,
          currentPhase: routed.payload.currentPhase || "",
          running: routed.payload.running,
          authoritativeRefreshRequested: true,
          latestMessageRole: routed.payload.latestMessage?.role || "",
          latestMessageContentLength: routed.payload.latestMessage?.contentLength ?? 0,
          latestMessageThoughtLength: routed.payload.latestMessage?.thoughtLength ?? 0,
          ...sessionStreamProtocolTelemetryFields(routed.trace),
        },
      });
    }

    function handleAssistantDelta(event: MessageEvent<string>) {
      if (disposed) {
        return;
      }
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "assistant_delta",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session assistant delta stream payload could not be parsed.");
        return;
      }
      markStreamConnected();
      queueAssistantDelta(routed.payload, routed.trace);
    }

    function logAppendGaps(gaps: SessionStreamAppendGap[], trace: SessionStreamProtocolTrace) {
      if (appendGapLogged) {
        return;
      }
      appendGapLogged = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.append_gap",
        message: "Session assistant delta append chain broke; snapshot resync was requested.",
        level: "warning",
        fields: {
          sessionId: streamSessionId,
          gapItemIds: gaps.slice(0, 5).map((gap) => gap.itemId).join(","),
          gapReasons: gaps.slice(0, 5).map((gap) => gap.reason).join(","),
          ...sessionStreamProtocolTelemetryFields(trace),
        },
      });
    }

    function handleStreamResume(event: MessageEvent<string>) {
      if (disposed) {
        return;
      }
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "stream_resume",
        rawData: event.data,
      });
      if (!routed.accepted) {
        return;
      }
      markStreamConnected();
      if (routed.payload.resume === "replayed" || routed.payload.resume === "partial") {
        // Journal replay frames are diagnostic only; the session detail query
        // remains authoritative for every replay outcome. Partial replay also
        // uses this refetch to restore the bounded-window gap.
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
      }
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.resumed",
        message: "Session stream resumed from the Last-Event-ID journal window.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          resume: routed.payload.resume,
          fromSeq: routed.payload.fromSeq,
          toSeq: routed.payload.toSeq,
          replayedCount: routed.payload.replayedCount ?? 0,
        },
      });
    }

    function handleSessionJournalEvent(event: MessageEvent<string>) {
      if (disposed) {
        return;
      }
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_journal_event",
        rawData: event.data,
      });
      if (!routed.accepted) {
        return;
      }
      markStreamConnected();
      if (journalReplayLogged) {
        return;
      }
      journalReplayLogged = true;
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.journal_replay_frame",
        message: "Session stream replayed a missed journal event after reconnect.",
        level: "info",
        fields: {
          sessionId: streamSessionId,
          replayedSeq: routed.payload.seq,
          eventType: routed.payload.eventType,
          payloadTruncated: Boolean(routed.payload.payloadTruncated),
        },
      });
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);
    stream.addEventListener("session_initial", handleSessionInitial as EventListener);
    stream.addEventListener("assistant_delta", handleAssistantDelta as EventListener);
    stream.addEventListener("stream_resume", handleStreamResume as EventListener);
    stream.addEventListener("session_journal_event", handleSessionJournalEvent as EventListener);

    return () => {
      // Route/session switch or unmount: detach this effect's projection state
      // synchronously BEFORE touching the UI. Any pending payload from the old
      // effect must be discarded, never applied to the React Query cache or the
      // active-turn layer. Cleanup cancels the coalesce timer and the
      // assistant-delta animation frame so no expensive main-thread work
      // outlives the old guarded stream. The stream itself is NOT closed here:
      // keep-warm release parks it (open) for SESSION_STREAM_WARM_MS so a
      // remount reuses the live connection; the registry's parked listeners
      // only record the ledger watermark and the stream is hard-closed once
      // the warm window expires.
      disposed = true;
      const readyStateBeforeClose = stream.readyState;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      if (assistantDeltaApplyFrame !== null) {
        window.cancelAnimationFrame(assistantDeltaApplyFrame);
        assistantDeltaApplyFrame = null;
      }
      pendingDetail = null;
      pendingDetailTrace = null;
      assistantDeltaScheduler.cancel();
      sessionStreamRecovery.dispose();
      setSessionStreamConnected(false);
      if (activeStreamRef.current?.stream === stream) {
        activeStreamRef.current = null;
      }
      if (forceCloseStreamRef.current === forceCloseStream) {
        forceCloseStreamRef.current = null;
      }
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.removeEventListener("session_initial", handleSessionInitial as EventListener);
      stream.removeEventListener("assistant_delta", handleAssistantDelta as EventListener);
      stream.removeEventListener("stream_resume", handleStreamResume as EventListener);
      stream.removeEventListener("session_journal_event", handleSessionJournalEvent as EventListener);
      releaseSessionStream(streamSessionId, stream);
      if (!closeTelemetryFired) {
        postBrowserTelemetry({
          phase: "session_stream",
          eventCode: "browser.session_stream.parked",
          message: "Session detail stream parked for reuse by the warm registry.",
          fields: {
            sessionId: streamSessionId,
            readyState: readyStateBeforeClose,
            warmMs: SESSION_STREAM_WARM_MS,
          },
        });
      }
    };
  }, [
    activeSessionId,
    createSessionEventStream,
    queryClient,
    syncSessionDetail,
    streamReconnectTick,
  ]);

  /**
   * Manual hard reconnect for the disconnect advisory button: closes the live
   * stream through the SAME owner path as the grace close (the tick bump
   * re-runs this effect and re-acquires via the keep-warm registry — never a
   * second connection) and requests one immediate authoritative refresh so a
   * stuck auto-reconnect loop cannot hide server-side progress.
   */
  const reconnectSessionStream = useCallback(() => {
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId || !forceCloseStreamRef.current) {
      return;
    }
    postBrowserTelemetry({
      phase: "session_stream",
      eventCode: "browser.session_stream.manual_reconnect_requested",
      message: "Manual session stream reconnect was requested from the disconnect advisory.",
      level: "info",
      fields: {
        sessionId: streamSessionId,
        pageInstanceId: getPageInstanceId(),
      },
    });
    void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
    forceCloseStreamRef.current("manual_reconnect");
  }, [activeSessionId, queryClient]);

  return { sessionStreamConnected, streamDisconnectedSinceMs, reconnectSessionStream };
}
