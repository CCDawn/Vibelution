import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import {
  activeTurnElapsedSeconds,
  formatActiveTurnHeartbeatText,
  resolveActiveTurnProgressStage,
  type ActiveTurnStatusMessageLike,
} from "./conversationActiveTurnStatusPresentation";
import styles from "./ConversationActiveTurnStatusNote.styles";

export type ConversationActiveTurnStatusNoteProps = {
  message: ActiveTurnStatusMessageLike & {
    timestamp?: string | null;
  };
  lang: "zh" | "en" | string;
  statusLabel?: string;
};

/**
 * Compact active-turn status: one heartbeat line without a redundant stage-dot track.
 */
export function ConversationActiveTurnStatusNote({
  message,
  lang,
  statusLabel,
}: ConversationActiveTurnStatusNoteProps) {
  const stage = resolveActiveTurnProgressStage(message);
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsedSeconds = activeTurnElapsedSeconds(message.timestamp, nowMs);
  const heartbeatText = formatActiveTurnHeartbeatText(stage, elapsedSeconds, lang);
  const resolvedStatusLabel = statusLabel
    || (lang === "en" ? "Status" : "状态");

  return (
    <div
      className={styles.note}
      role="status"
      aria-live="polite"
      aria-label={[resolvedStatusLabel, heartbeatText].filter(Boolean).join(" · ")}
      data-active-turn-stage={stage}
      data-active-turn-elapsed-seconds={elapsedSeconds ?? ""}
    >
      <span className={styles.label}>{resolvedStatusLabel}</span>
      <div className={styles.body}>
        <span className={styles.textRow}>
          <LoaderCircle className={styles.spinner} size={14} aria-hidden="true" />
          <span className={styles.text}>{heartbeatText}</span>
        </span>
      </div>
    </div>
  );
}
