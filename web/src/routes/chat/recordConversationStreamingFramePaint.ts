import { postBrowserTelemetry } from "../../app/browserTelemetry";
import type { ConversationStreamingFramePaintMetrics } from "../../components/conversation/conversationStreamingMetrics";
import {
  activeTurnLayerTextLength,
  runningToolPaintKeys,
  selectFirstUnpaintedRunningTool,
  toolStartToFirstPaintMs,
  type ActiveTurnLayerState,
} from "../chatActiveTurnLayer";
import { chatStreamPerformanceNowMs } from "./chatCodingRouteViewModel";
import type { ActiveTurnLayersState } from "./activeTurnLayersStore";

type MutableRef<T> = { current: T };
const firstPaintByLayer = new WeakMap<ActiveTurnLayerState, { atMs: number; reported: boolean }>();

/**
 * Frame-paint telemetry for the active conversation turn.
 * Reads the latest committed turn layer from the store ref so a painted frame
 * does not re-render the workbench. Timing belongs to the rendered turn/frame,
 * never to the last update of a session that may have moved on to another turn.
 */
export function recordConversationStreamingFramePaint({
  metrics,
  activeSessionId,
  activeTurnLayersBySessionRef,
  paintedRunningToolIdsBySessionRef,
  firstPaintedRunningToolAtBySessionRef,
  lastConversationStreamingFrameTelemetryAtRef,
}: {
  metrics: ConversationStreamingFramePaintMetrics;
  activeSessionId: string | null;
  activeTurnLayersBySessionRef: MutableRef<ActiveTurnLayersState>;
  paintedRunningToolIdsBySessionRef: MutableRef<Record<string, string[]>>;
  firstPaintedRunningToolAtBySessionRef: MutableRef<Record<string, Record<string, number>>>;
  lastConversationStreamingFrameTelemetryAtRef: MutableRef<Record<string, number>>;
  /** Legacy caller reference; session-only stamps cannot identify a frame. */
  lastAssistantDeltaAppliedAtRef?: MutableRef<Record<string, number>>;
}) {
  const sessionId = String(metrics.sessionId || "").trim();
  if (!sessionId || sessionId !== activeSessionId) {
    return;
  }
  const now = Date.now();
  const paintedActiveTurn = activeTurnLayersBySessionRef.current[sessionId];
  if (!paintedActiveTurn || !metrics.turnId || metrics.turnId !== paintedActiveTurn.turnId
    || metrics.ledgerSeq !== paintedActiveTurn.ledgerSeq) return;
  const paintedAtMs = metrics.paintedAtMs;
  const anchor = paintedActiveTurn.clientDeltaTiming;
  const appliedAtMs = metrics.assistantDeltaAppliedAtMs;
  const timingMatches = anchor?.turnId === metrics.turnId && anchor.ledgerSeq === metrics.ledgerSeq
    && anchor.appliedAtMs === appliedAtMs && typeof appliedAtMs === "number"
    && Number.isFinite(appliedAtMs) && appliedAtMs >= 0
    && Number.isFinite(paintedAtMs) && paintedAtMs >= appliedAtMs;
  let firstPaint = firstPaintByLayer.get(paintedActiveTurn);
  if (timingMatches && !firstPaint) {
    firstPaint = { atMs: paintedAtMs, reported: false };
    firstPaintByLayer.set(paintedActiveTurn, firstPaint);
  }
  const paintedToolSelection = selectFirstUnpaintedRunningTool(
    paintedActiveTurn,
    paintedRunningToolIdsBySessionRef.current[sessionId] ?? [],
  );
  const newlyPaintedRunningTool = paintedToolSelection.tool;
  const newlyPaintedRunningTools = paintedToolSelection.tools;
  const firstPaintedToolAtById = {
    ...(firstPaintedRunningToolAtBySessionRef.current[sessionId] ?? {}),
  };
  const runningPaintKeys = runningToolPaintKeys(paintedActiveTurn);
  runningPaintKeys.forEach(({ toolId, fallbackKey, ordinalKey }) => {
    [toolId, fallbackKey, ordinalKey].filter(Boolean).forEach((key) => {
      if (!Number.isFinite(firstPaintedToolAtById[key])) {
        firstPaintedToolAtById[key] = now;
      }
    });
  });
  firstPaintedRunningToolAtBySessionRef.current = {
    ...firstPaintedRunningToolAtBySessionRef.current,
    [sessionId]: firstPaintedToolAtById,
  };
  const lastLoggedAt = lastConversationStreamingFrameTelemetryAtRef.current[sessionId] ?? 0;
  if (now - lastLoggedAt < 1_000 && !newlyPaintedRunningTool) {
    return;
  }
  if (newlyPaintedRunningTools.length > 0) {
    const newlyPaintedFallbackKeys = paintedToolSelection.toolIds.flatMap((toolId) => {
      const keys = runningPaintKeys.find((key) => key.toolId === toolId);
      return keys ? [keys.fallbackKey, keys.ordinalKey] : [];
    }).filter(Boolean);
    paintedRunningToolIdsBySessionRef.current = {
      ...paintedRunningToolIdsBySessionRef.current,
      [sessionId]: Array.from(new Set([
        ...(paintedRunningToolIdsBySessionRef.current[sessionId] ?? []),
        ...paintedToolSelection.toolIds,
        ...newlyPaintedFallbackKeys,
      ])).slice(-64),
    };
  }
  const toolStartToBrowserPaintMs = newlyPaintedRunningTools.reduce((maximum, tool, index) => {
    const toolId = paintedToolSelection.toolIds[index];
    const paintKeys = runningPaintKeys.find((key) => key.toolId === toolId);
    const firstPaintCandidates = [
      firstPaintedToolAtById[toolId],
      firstPaintedToolAtById[paintKeys?.fallbackKey ?? ""],
      firstPaintedToolAtById[paintKeys?.ordinalKey ?? ""],
    ]
      .filter(Number.isFinite);
    const firstPaintedAt = firstPaintCandidates.length > 0 ? Math.min(...firstPaintCandidates) : undefined;
    return Math.max(maximum, toolStartToFirstPaintMs(tool, firstPaintedAt, now));
  }, 0);
  lastConversationStreamingFrameTelemetryAtRef.current = {
    ...lastConversationStreamingFrameTelemetryAtRef.current,
    [sessionId]: now,
  };
  const reportTiming = timingMatches && firstPaint && !firstPaint.reported;
  if (reportTiming && firstPaint) firstPaint.reported = true;
  postBrowserTelemetry({
    phase: "conversation_stream",
    eventCode: "browser.conversation_stream.frame_painted",
    message: "Conversation streaming frame was committed by the conversation view.",
    level: "info",
    fields: {
      sessionId,
      turnId: paintedActiveTurn?.turnId ?? "",
      ledgerSeq: paintedActiveTurn.ledgerSeq,
      streamingMessageCount: metrics.streamingMessageCount,
      renderedTextLength: metrics.renderedTextLength,
      scrollSignalLength: metrics.scrollSignal.length,
      activeTurnTextLength: activeTurnLayerTextLength(paintedActiveTurn),
      paintedAtMs: Math.round(Number.isFinite(paintedAtMs) ? paintedAtMs : chatStreamPerformanceNowMs()),
      applyToPaintObserved: Boolean(reportTiming),
      ...(reportTiming && firstPaint ? {
        lastAssistantDeltaAppliedAtMs: Math.round(appliedAtMs),
        applyToPaintMs: Math.round(firstPaint.atMs - appliedAtMs),
      } : {}),
      toolStartToBrowserPaintMs: Math.max(0, toolStartToBrowserPaintMs),
      activeStatusSource: paintedActiveTurn?.ledgerSeq ? "assistant_delta" : "optimistic_submit",
    },
  });
}
