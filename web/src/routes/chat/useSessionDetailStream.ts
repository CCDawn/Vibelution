import { useEffect, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { QueryClient } from "@tanstack/react-query";

import { collectBrowserPageSnapshot, postBrowserTelemetry } from "../../app/browserTelemetry";
import { getPageInstanceId } from "../../app/pageInstance";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionStreamEvent } from "../../api/types";
import {
  isActiveTurnSettledByDetail,
  setActiveTurnLayerForSession,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import {
  routeSessionStreamEvent,
  sessionStreamProtocolTelemetryFields,
  type SessionStreamProtocolTrace,
} from "../chatSessionStreamProtocol";
import {
  planAppliedAssistantDeltaDrain,
  planAppliedSessionDetail,
  planQueuedSessionDetail,
  type SessionStreamApplyStats,
} from "../chatStreamApplyController";
import { createSessionAssistantDeltaScheduler } from "../sessionAssistantDeltaScheduler";
import { chatStreamPerformanceNowMs, isBusyPhase } from "./chatCodingRouteViewModel";
import {
  SESSION_STREAM_MIN_APPLY_INTERVAL_MS,
  type SessionStreamDecisionSnapshot,
} from "./chatSessionStreamConnect";

type DesktopConversationNotifier = {
  handleSessionDetail: (
    detail: SessionDetail,
    options: { sessionTitle: string },
  ) => void;
  handleAssistantDelta: (
    payload: Extract<SessionStreamEvent, { type: "assistant_delta" }>,
    options: { sessionTitle: string },
  ) => void;
};

export type UseSessionDetailStreamOptions = {
  activeSessionId: string | null | undefined;
  sessionStreamShouldConnect: boolean;
  queryClient: QueryClient;
  syncSessionDetail: (detail: SessionDetail) => void;
  setActiveTurnLayersBySession: Dispatch<SetStateAction<Record<string, ActiveTurnLayerState>>>;
  activeTurnLayersBySessionRef: MutableRefObject<Record<string, ActiveTurnLayerState>>;
  lastAssistantDeltaAppliedAtRef: MutableRefObject<Record<string, number>>;
  sessionStreamDecisionSnapshotRef: MutableRefObject<SessionStreamDecisionSnapshot>;
  desktopConversationNotifierRef: MutableRefObject<DesktopConversationNotifier>;
  /** Live title for desktop notifications (detail title or summary title). */
  sessionTitleForNotifications: string;
};

/**
 * Sole owner of the direct-session detail EventSource.
 * Do not open a second /api/sessions/:id/events connection elsewhere.
 */
export function useSessionDetailStream({
  activeSessionId,
  sessionStreamShouldConnect,
  queryClient,
  syncSessionDetail,
  setActiveTurnLayersBySession,
  activeTurnLayersBySessionRef,
  lastAssistantDeltaAppliedAtRef,
  sessionStreamDecisionSnapshotRef,
  desktopConversationNotifierRef,
  sessionTitleForNotifications,
}: UseSessionDetailStreamOptions): { sessionStreamConnected: boolean } {
  const [sessionStreamConnected, setSessionStreamConnected] = useState(false);
  const sessionStreamErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamPayloadErrorLoggedRef = useRef<Record<string, boolean>>({});
  const sessionStreamApplyStatsRef = useRef<Record<string, SessionStreamApplyStats>>({});
  const sessionTitleForNotificationsRef = useRef(sessionTitleForNotifications);
  sessionTitleForNotificationsRef.current = sessionTitleForNotifications;

  useEffect(() => {
    if (!sessionStreamShouldConnect || typeof EventSource === "undefined") {
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
          eventSourceAvailable: typeof EventSource !== "undefined",
          pageInstanceId: getPageInstanceId(),
          ...collectBrowserPageSnapshot(),
        },
      });
      return;
    }

    let disposed = false;
    const streamSessionId = String(activeSessionId || "");
    if (!streamSessionId) {
      setSessionStreamConnected(false);
      return;
    }
    let pendingDetail: SessionDetail | null = null;
    let pendingDetailTrace: SessionStreamProtocolTrace | null = null;
    let applyTimer: number | null = null;
    let lastAppliedAt = 0;
    let committedAssistantDeltaLayer: ActiveTurnLayerState | undefined = activeTurnLayersBySessionRef.current[streamSessionId];
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
    const stream = new EventSource(`/api/sessions/${streamSessionId}/events?initial=none`);

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
      const detail = pendingDetail;
      const trace = pendingDetailTrace;
      pendingDetail = null;
      pendingDetailTrace = null;
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
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
      syncSessionDetail(detail);
      desktopConversationNotifierRef.current.handleSessionDetail(detail, {
        sessionTitle: detail.title || detail.id,
      });
      if (decision.clearActiveLayer) {
        committedAssistantDeltaLayer = undefined;
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, undefined)
        );
      }
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
      if (assistantDeltaScheduler.pendingCount === 0 || disposed) {
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
      });
      if (!decision.applied) {
        return;
      }
      committedAssistantDeltaLayer = decision.nextCommittedLayer;
      if (decision.shouldCommitRender) {
        setActiveTurnLayersBySession((current) =>
          setActiveTurnLayerForSession(current, streamSessionId, decision.nextCommittedLayer)
        );
      }
      sessionStreamApplyStatsRef.current[streamSessionId] = decision.stats;
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
      const queued = assistantDeltaScheduler.enqueue(payload, trace.payloadLength, trace);
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
            turnId: payload.turnId,
            stage: payload.stage,
            receivedCount: stats.received,
            appliedCount: stats.applied,
            droppedCount: stats.dropped,
            payloadLength: trace.payloadLength,
            contentDeltaLength: queued.contentDeltaLength,
            thoughtDeltaLength: queued.thoughtDeltaLength,
            pendingTextLength: 0,
            batchSize: queued.pendingCount,
            done: payload.done,
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
        setSessionStreamConnected(true);
        sessionStreamErrorLoggedRef.current[streamSessionId] = false;
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
        const pendingAssistantDeltaCount = assistantDeltaScheduler.pendingCount;
        applyPendingAssistantDeltas("close");
        void queryClient.invalidateQueries({ queryKey: queryKeys.session(streamSessionId) });
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
            },
          });
        }
      }
    };

    function handleSessionDetail(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_detail",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session detail stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
      queueSessionDetail(routed.payload.detail, routed.trace);
    }

    function handleSessionInitial(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "session_initial",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session initial stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
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
          latestMessageRole: routed.payload.latestMessage?.role || "",
          latestMessageContentLength: routed.payload.latestMessage?.contentLength ?? 0,
          latestMessageThoughtLength: routed.payload.latestMessage?.thoughtLength ?? 0,
          ...sessionStreamProtocolTelemetryFields(routed.trace),
        },
      });
    }

    function handleAssistantDelta(event: MessageEvent<string>) {
      const routed = routeSessionStreamEvent({
        activeSessionId: streamSessionId,
        expectedType: "assistant_delta",
        rawData: event.data,
      });
      if (!routed.accepted) {
        logRejectedSessionStreamRoute(routed.trace, "Session assistant delta stream payload could not be parsed.");
        return;
      }
      setSessionStreamConnected(true);
      desktopConversationNotifierRef.current.handleAssistantDelta(routed.payload, {
        sessionTitle: sessionTitleForNotificationsRef.current || streamSessionId,
      });
      queueAssistantDelta(routed.payload, routed.trace);
    }

    stream.addEventListener("session_detail", handleSessionDetail as EventListener);
    stream.addEventListener("session_initial", handleSessionInitial as EventListener);
    stream.addEventListener("assistant_delta", handleAssistantDelta as EventListener);

    return () => {
      const readyStateBeforeClose = stream.readyState;
      applyPendingAssistantDeltas("close");
      applyPendingDetail("close");
      disposed = true;
      setSessionStreamConnected(false);
      if (applyTimer) {
        window.clearTimeout(applyTimer);
        applyTimer = null;
      }
      if (assistantDeltaApplyFrame !== null) {
        window.cancelAnimationFrame(assistantDeltaApplyFrame);
        assistantDeltaApplyFrame = null;
      }
      stream.removeEventListener("session_detail", handleSessionDetail as EventListener);
      stream.removeEventListener("session_initial", handleSessionInitial as EventListener);
      stream.removeEventListener("assistant_delta", handleAssistantDelta as EventListener);
      stream.close();
      postBrowserTelemetry({
        phase: "session_stream",
        eventCode: "browser.session_stream.closed",
        message: "Session detail stream closed.",
        fields: {
          sessionId: streamSessionId,
          readyState: readyStateBeforeClose,
        },
      });
    };
  }, [
    activeSessionId,
    queryClient,
    sessionStreamShouldConnect,
    syncSessionDetail,
  ]);

  return { sessionStreamConnected };
}
