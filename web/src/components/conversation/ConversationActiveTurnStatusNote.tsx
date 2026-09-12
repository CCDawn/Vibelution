import { LoaderCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  activeTurnElapsedSeconds,
  formatActiveTurnHeartbeatText,
  planActiveTurnStageSwitch,
  resolveActiveTurnProgressStage,
  resolveActiveTurnRetryProgress,
  type ActiveTurnStatusMessageLike,
} from "./conversationActiveTurnStatusPresentation";
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

  const elapsedSeconds = activeTurnElapsedSeconds(message.timestamp, nowMs);
  const retryProgress = stage === "model_retry" || stage === "retrying"
    ? resolveActiveTurnRetryProgress(message)
    : null;
  const heartbeatText = companionMode
    ? (lang === "en" ? "Typing…" : "正在输入…")
    : formatActiveTurnHeartbeatText(stage, elapsedSeconds, lang, retryProgress);
  const resolvedStatusLabel = statusLabel
    || (lang === "en" ? "Status" : "状态");

  return (
    <div
      className={styles.note}
      role="status"
      aria-live="polite"
      aria-label={companionMode ? undefined : [resolvedStatusLabel, heartbeatText].filter(Boolean).join(" · ")}
      data-active-turn-stage={stage}
      data-active-turn-elapsed-seconds={elapsedSeconds ?? ""}
      data-companion-typing-status={companionMode ? "true" : undefined}
    >
      {!companionMode ? <span className={styles.label}>{resolvedStatusLabel}</span> : null}
      <div className={styles.body}>
        <span className={styles.textRow}>
          <LoaderCircle className={styles.spinner} size={14} aria-hidden="true" />
          <span className={styles.text}>{heartbeatText}</span>
        </span>
      </div>
    </div>
  );
}
