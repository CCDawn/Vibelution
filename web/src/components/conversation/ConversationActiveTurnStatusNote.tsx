import { useNowTick } from "../../app/useNowTick";
import { Brain, ChevronRight, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { VButton, VNativeButton, VStatusChip } from "../vui";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  ACTIVE_TURN_RECONNECT_ACTION_COOLDOWN_MS,
  activeTurnElapsedSeconds,
  activeTurnStageBarPhase,
  activeTurnStageSegmentSeconds,
  formatActiveTurnHeartbeatText,
  planActiveTurnStageSwitch,
  resolveActiveTurnDisconnectSeconds,
  resolveActiveTurnProgressStage,
  resolveActiveTurnRetryProgress,
  resolveActiveTurnRouteFallback,
  resolveActiveTurnReasoningSummary,
  resolveActiveTurnStallSeconds,
  shouldShowActiveTurnReconnectAction,
  splitActiveTurnHeartbeatText,
  shouldShowNoOutputStall,
  visibleActiveTurnRetryProgress,
  type ActiveTurnStatusMessageLike,
} from "./conversationActiveTurnStatusPresentation";
import { useActiveTurnStreamState } from "./activeTurnStreamState";
import styles from "./ConversationActiveTurnStatusNote.styles";

export type ConversationActiveTurnStatusNoteProps = {
  message: ActiveTurnStatusMessageLike & {
    timestamp?: string | null;
  };
  lang: "zh" | "en" | string;
  statusLabel?: string;
  /** Companion sessions intentionally collapse all in-flight detail to one chat affordance. */
  companionMode?: boolean;
  /** Session phase. `"stopping"` replaces the heartbeat on the first paint. */
  phase?: string;
  /** A visible work disclosure owns routine progress; keep only exceptional feedback here. */
  advisoriesOnly?: boolean;
  /** Live reasoning text for the current turn: drives the streaming preview and the expandable body. */
  reasoningText?: string;
};

/**
 * Compact active-turn status: one heartbeat line without a redundant stage-dot track.
 * Stream-connectivity advisories (disconnected / stalled / route fallback) are
 * projected from the guarded stream state through ActiveTurnStreamStateContext.
 */
export function ConversationActiveTurnStatusNote({
  message,
  lang,
  statusLabel,
  companionMode = false,
  phase = "",
  advisoriesOnly = false,
  reasoningText = "",
}: ConversationActiveTurnStatusNoteProps) {
  const resolvedStage = resolveActiveTurnProgressStage(message);
  const stopping = phase === "stopping";
  const [stage, setStage] = useState(stopping ? "stopping" : resolvedStage);
  const displayStage = stopping ? "stopping" : stage;
  const stageShownAtRef = useRef(Date.now());
  // Thinking shows the shimmering label and a preview, never a counter, so it
  // must not hold a clock: an idle clock is a render per second for text that
  // cannot change.
  const heartbeatActive = activeTurnStageBarPhase(displayStage) === "thinking";
  const nowMs = useNowTick(!companionMode && !heartbeatActive);
  const streamState = useActiveTurnStreamState();
  // ZCode keeps the reasoning block collapsed while streaming, so the row shows
  // one preview line and the full text only on an explicit open.
  const [thinkingExpanded, setThinkingExpanded] = useState(false);
  const summaryViewportRef = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    if (companionMode || stopping) {
      return undefined;
    }
    const plan = planActiveTurnStageSwitch(stage, resolvedStage, Date.now() - stageShownAtRef.current);
    if (plan.stage !== stage) {
      stageShownAtRef.current = Date.now();
      setStage(plan.stage);
      return undefined;
    }
    if (plan.delayMs <= 0) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      stageShownAtRef.current = Date.now();
      setStage(resolvedStage);
    }, plan.delayMs);
    return () => window.clearTimeout(timer);
  }, [resolvedStage, stage, companionMode, stopping]);

  // ZCode reasoning-block semantics: the heartbeat bills the current thinking
  // segment, not the whole turn. A segment starts when the displayed stage
  // enters the thinking family and resets when it leaves. Until the first
  // effect tick the segment counts from the current frame (static renders
  // show 0s), never the turn start.
  const thinkingSegmentStartedAtRef = useRef<number | null>(null);
  useEffect(() => {
    if (activeTurnStageBarPhase(stage) === "thinking") {
      if (thinkingSegmentStartedAtRef.current === null) {
        thinkingSegmentStartedAtRef.current = Date.now();
      }
      return;
    }
    thinkingSegmentStartedAtRef.current = null;
  }, [stage]);

  const langKey = lang === "en" ? "en" : "zh";
  const elapsedSeconds = activeTurnElapsedSeconds(message.timestamp, nowMs);
  const thinkingSegmentSeconds = activeTurnStageSegmentSeconds({
    stage,
    segmentStartedAtMs: thinkingSegmentStartedAtRef.current
      ?? (activeTurnStageBarPhase(stage) === "thinking" ? nowMs : null),
    nowMs,
  });
  const retryProgress = displayStage === "model_retry" || displayStage === "retrying"
    ? resolveActiveTurnRetryProgress(message)
    : null;
  // ZCode semantics: retries 1-2 stay silent on the heartbeat; from the third
  // attempt the counter becomes visible and earns the shimmer treatment.
  const visibleRetryProgress = companionMode || displayStage === "stopping"
    ? null
    : visibleActiveTurnRetryProgress(retryProgress);
  const heartbeatText = displayStage === "stopping"
    ? formatActiveTurnHeartbeatText("stopping", elapsedSeconds, lang)
    : companionMode
      ? (lang === "en" ? "Typing…" : "正在输入…")
      : formatActiveTurnHeartbeatText(stage, thinkingSegmentSeconds ?? elapsedSeconds, lang, retryProgress);
  const { head: heartbeatHead, duration: heartbeatDuration } = splitActiveTurnHeartbeatText(heartbeatText);
  // Activity is carried by the type (a shimmer sweep), not by a spinner: the
  // heartbeat can live for minutes, and a rotating loader next to the avatar
  // becomes a second focal point that never settles.
  // ZCode shows the shimmering label alone while the reasoning stream is live;
  // the duration belongs to the settled block, not to the wait. Other stages
  // (queued / requesting / generating / stopping) keep their counter.
  const visibleDuration = heartbeatActive ? "" : heartbeatDuration;
  const displayHeartbeatText = visibleDuration
    ? `${heartbeatHead} · ${visibleDuration}`
    : heartbeatHead;
  const reasoningSummary = !advisoriesOnly && heartbeatActive
    ? resolveActiveTurnReasoningSummary(reasoningText)
    : "";
  const canExpandThinking = !companionMode
    && !advisoriesOnly
    && heartbeatActive
    && Boolean(reasoningText.trim());

  useEffect(() => {
    const viewport = summaryViewportRef.current;
    if (!viewport) {
      return;
    }
    // The newest tokens must win the single line; older text slides left.
    viewport.scrollLeft = viewport.scrollWidth;
  }, [reasoningSummary]);
  const resolvedStatusLabel = statusLabel
    || (lang === "en" ? "Status" : "状态");

  // Connectivity advisories stay out of companion mode: it collapses all
  // in-flight detail into the single typing affordance by design.
  const disconnectSeconds = companionMode
    ? null
    : resolveActiveTurnDisconnectSeconds({
      streamConnected: streamState.streamConnected,
      streamDisconnectedSinceMs: streamState.streamDisconnectedSinceMs,
      nowMs,
    });
  // Stall baseline: the fresher of the live activity stamp (any applied stream
  // event — received is not applied) and the body-delta timestamp; with
  // neither, the turn start fills in inside resolveActiveTurnStallSeconds.
  const lastStreamActivityAtMs = streamState.lastStreamActivityAtMs?.() ?? 0;
  const lastDeltaAtMs = streamState.lastAssistantDeltaAtMs ?? 0;
  const stallBaselineAtMs = Math.max(lastStreamActivityAtMs, lastDeltaAtMs) || lastDeltaAtMs || null;
  const stallSeconds = companionMode
    ? null
    : resolveActiveTurnStallSeconds({
      lastAssistantDeltaAtMs: stallBaselineAtMs,
      turnStartedAt: message.timestamp,
      nowMs,
    });
  // Thinking/tool/queue silence is the normal agentic shape; only the
  // body-streaming stage surfaces the "no output — you can stop" hint.
  const showNoOutputStall = stallSeconds !== null && shouldShowNoOutputStall(displayStage);
  const routeFallback = companionMode ? null : resolveActiveTurnRouteFallback(message);

  // Manual reconnect affordance: only while a real reconnect loop is showing
  // AND the stream owner wired its action through the context (companion
  // surfaces and supervised panels pass no handler, so no dead button).
  const [reconnectPending, setReconnectPending] = useState(false);
  const reconnectCooldownTimerRef = useRef<number | null>(null);
  useEffect(() => () => {
    if (reconnectCooldownTimerRef.current !== null) {
      window.clearTimeout(reconnectCooldownTimerRef.current);
      reconnectCooldownTimerRef.current = null;
    }
  }, []);
  useEffect(() => {
    // A fresh disconnect episode gets a fresh button: clear the stale cooldown
    // so a second drop right after recovery is still actionable.
    if (disconnectSeconds === null && reconnectCooldownTimerRef.current !== null) {
      window.clearTimeout(reconnectCooldownTimerRef.current);
      reconnectCooldownTimerRef.current = null;
      setReconnectPending(false);
    }
  }, [disconnectSeconds]);
  const showReconnectAction = shouldShowActiveTurnReconnectAction({
    disconnectSeconds,
    hasReconnectHandler: typeof streamState.reconnectSessionStream === "function",
  });
  const handleReconnectStream = () => {
    if (reconnectPending) {
      return;
    }
    setReconnectPending(true);
    if (reconnectCooldownTimerRef.current !== null) {
      window.clearTimeout(reconnectCooldownTimerRef.current);
    }
    reconnectCooldownTimerRef.current = window.setTimeout(() => {
      reconnectCooldownTimerRef.current = null;
      setReconnectPending(false);
    }, ACTIVE_TURN_RECONNECT_ACTION_COOLDOWN_MS);
    streamState.reconnectSessionStream?.();
  };
  const reconnectLabel = dictionaryChat[langKey].reconnectStream;
  const showHeartbeat = !advisoriesOnly || companionMode || stopping || Boolean(visibleRetryProgress);
  if (!showHeartbeat && disconnectSeconds === null && !showNoOutputStall && !routeFallback) {
    return null;
  }

  return (
    <div
      className={showHeartbeat ? styles.note : styles.advisoryNote}
      role="status"
      aria-live="polite"
      aria-label={companionMode || !showHeartbeat ? undefined : [resolvedStatusLabel, displayHeartbeatText].filter(Boolean).join(" · ")}
      data-active-turn-stage={displayStage}
      data-active-turn-elapsed-seconds={elapsedSeconds ?? ""}
      data-active-turn-retry-attempt={visibleRetryProgress ? visibleRetryProgress.attempt : undefined}
      data-active-turn-disconnected={disconnectSeconds !== null ? "true" : undefined}
      data-active-turn-stalled={showNoOutputStall ? "true" : undefined}
      data-active-turn-route-fallback={routeFallback ? "true" : undefined}
      data-companion-typing-status={companionMode ? "true" : undefined}
    >
      {!companionMode && showHeartbeat ? <span className={styles.label}>{resolvedStatusLabel}</span> : null}
      <div className={styles.body}>
        {showHeartbeat ? (
          <VNativeButton
            className={styles.textRow}
            aria-expanded={canExpandThinking ? thinkingExpanded : undefined}
            aria-label={canExpandThinking
              ? (langKey === "zh"
                ? (thinkingExpanded ? "收起思考" : "展开思考")
                : (thinkingExpanded ? "Hide reasoning" : "Show reasoning"))
              : undefined}
            data-testid="active-turn-heartbeat"
            data-active-turn-thinking-expanded={thinkingExpanded ? "true" : undefined}
            onClick={canExpandThinking
              ? () => setThinkingExpanded((current) => !current)
              : undefined}
          >
            <Brain className={styles.icon} size={16} aria-hidden="true" />
            <span className={styles.text}>
              <span
                className={heartbeatActive || visibleRetryProgress
                  ? `${styles.textHead} ${styles.retryShimmer}`
                  : styles.textHead}
              >
                {heartbeatHead}
              </span>
              {visibleDuration ? (
                <span className={styles.duration}>{` · ${visibleDuration}`}</span>
              ) : null}
            </span>
            {reasoningSummary && !thinkingExpanded ? (
              <>
                <span className={styles.duration}>·</span>
                <span
                  ref={summaryViewportRef}
                  className={styles.summary}
                  data-active-turn-reasoning-summary="true"
                >
                  <span className={styles.summaryText}>{reasoningSummary}</span>
                </span>
              </>
            ) : null}
            {canExpandThinking ? (
              <ChevronRight
                className={styles.chevron}
                data-active-turn-thinking-chevron={thinkingExpanded ? "expanded" : "collapsed"}
                size={14}
                aria-hidden="true"
              />
            ) : null}
          </VNativeButton>
        ) : null}
        {canExpandThinking && thinkingExpanded && reasoningText.trim() ? (
          <div className={styles.thinkingBody} data-active-turn-thinking-body="true">
            {reasoningText}
          </div>
        ) : null}
        {disconnectSeconds !== null ? (
          <VStatusChip
            tone="warning"
            className={styles.advisory}
            data-testid="active-turn-disconnected"
          >
            {`${dictionaryChat[langKey].chatStreamDisconnectedReconnecting}${disconnectSeconds > 0 ? ` · ${disconnectSeconds}s` : ""}`}
          </VStatusChip>
        ) : null}
        {showReconnectAction ? (
          <VButton
            variant="ghost"
            density="compact"
            className={styles.reconnectAction}
            icon={<RotateCw size={14} aria-hidden="true" />}
            isDisabled={reconnectPending}
            aria-label={reconnectLabel}
            data-testid="active-turn-reconnect"
            data-active-turn-reconnect-pending={reconnectPending ? "true" : undefined}
            onClick={handleReconnectStream}
          >
            {reconnectLabel}
          </VButton>
        ) : null}
        {showNoOutputStall ? (
          <VStatusChip
            tone="warning"
            className={styles.advisory}
            data-testid="active-turn-stalled"
          >
            {`${dictionaryChat[langKey].chatStreamNoOutputStalled} · ${stallSeconds}s`}
          </VStatusChip>
        ) : null}
        {routeFallback ? (
          <VStatusChip
            tone="accent"
            className={styles.advisory}
            data-testid="active-turn-route-fallback"
          >
            {dictionaryChat[langKey]
              .chatRouteFallbackSwitched
              .replace("{from}", routeFallback.from)
              .replace("{to}", routeFallback.to)}
          </VStatusChip>
        ) : null}
      </div>
    </div>
  );
}
