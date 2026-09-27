import { LoaderCircle, RotateCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { VButton, VStatusChip } from "../vui";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  ACTIVE_TURN_RECONNECT_ACTION_COOLDOWN_MS,
  activeTurnElapsedSeconds,
  formatActiveTurnHeartbeatText,
  planActiveTurnStageSwitch,
  resolveActiveTurnDisconnectSeconds,
  resolveActiveTurnProgressStage,
  resolveActiveTurnRetryProgress,
  resolveActiveTurnRouteFallback,
  resolveActiveTurnStallSeconds,
  shouldShowActiveTurnReconnectAction,
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
}: ConversationActiveTurnStatusNoteProps) {
  const resolvedStage = resolveActiveTurnProgressStage(message);
  const [stage, setStage] = useState(resolvedStage);
  const stageShownAtRef = useRef(Date.now());
  const [nowMs, setNowMs] = useState(() => Date.now());
  const streamState = useActiveTurnStreamState();

  useEffect(() => {
    if (companionMode) {
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
  }, [resolvedStage, stage, companionMode]);

  useEffect(() => {
    if (companionMode) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, [companionMode]);

  const langKey = lang === "en" ? "en" : "zh";
  const elapsedSeconds = activeTurnElapsedSeconds(message.timestamp, nowMs);
  const retryProgress = stage === "model_retry" || stage === "retrying"
    ? resolveActiveTurnRetryProgress(message)
    : null;
  // ZCode semantics: retries 1-2 stay silent on the heartbeat; from the third
  // attempt the counter becomes visible and earns the shimmer treatment.
  const visibleRetryProgress = companionMode
    ? null
    : visibleActiveTurnRetryProgress(retryProgress);
  const heartbeatText = companionMode
    ? (lang === "en" ? "Typing…" : "正在输入…")
    : formatActiveTurnHeartbeatText(stage, elapsedSeconds, lang, retryProgress);
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
  const stallSeconds = companionMode
    ? null
    : resolveActiveTurnStallSeconds({
      lastAssistantDeltaAtMs: streamState.lastAssistantDeltaAtMs,
      turnStartedAt: message.timestamp,
      nowMs,
    });
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

  return (
    <div
      className={styles.note}
      role="status"
      aria-live="polite"
      aria-label={companionMode ? undefined : [resolvedStatusLabel, heartbeatText].filter(Boolean).join(" · ")}
      data-active-turn-stage={stage}
      data-active-turn-elapsed-seconds={elapsedSeconds ?? ""}
      data-active-turn-retry-attempt={visibleRetryProgress ? visibleRetryProgress.attempt : undefined}
      data-active-turn-disconnected={disconnectSeconds !== null ? "true" : undefined}
      data-active-turn-stalled={stallSeconds !== null ? "true" : undefined}
      data-active-turn-route-fallback={routeFallback ? "true" : undefined}
      data-companion-typing-status={companionMode ? "true" : undefined}
    >
      {!companionMode ? <span className={styles.label}>{resolvedStatusLabel}</span> : null}
      <div className={styles.body}>
        <span className={styles.textRow}>
          <LoaderCircle className={styles.spinner} size={14} aria-hidden="true" />
          <span
            className={visibleRetryProgress ? `${styles.text} ${styles.retryShimmer}` : styles.text}
          >
            {heartbeatText}
          </span>
        </span>
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
        {stallSeconds !== null ? (
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
