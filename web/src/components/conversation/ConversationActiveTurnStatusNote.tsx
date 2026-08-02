import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import {
  activeTurnElapsedSeconds,
  buildActiveTurnStageBarItems,
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
  showStageBar?: boolean;
};

/**
 * Compact active-turn status with live heartbeat seconds + stage bar.
 * Timer lives here so ConversationView stays free of setInterval.
 */
export function ConversationActiveTurnStatusNote({
  message,
  lang,
  statusLabel,
  showStageBar = true,
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
  const stageBarItems = showStageBar ? buildActiveTurnStageBarItems(stage, lang) : [];
  const resolvedStatusLabel = statusLabel
    || (lang === "en" ? "Status" : "状态");

  return (
    <div
      className={styles.note}
      role="status"
      aria-live="polite"
      data-active-turn-stage={stage}
      data-active-turn-elapsed-seconds={elapsedSeconds ?? ""}
    >
      <span className={styles.label}>{resolvedStatusLabel}</span>
      <div className={styles.body}>
        <span className={styles.textRow}>
          <LoaderCircle className={styles.spinner} size={14} aria-hidden="true" />
          <span className={styles.text}>{heartbeatText}</span>
        </span>
        {stageBarItems.length > 0 ? (
          <span className={styles.stageBar} aria-hidden="true">
            {stageBarItems.map((item, index) => (
              <span key={item.phase} className="inline-flex items-center gap-1">
                {index > 0 ? <span className={styles.stageSeparator}>→</span> : null}
                <span
                  className={
                    item.current
                      ? styles.stageItemCurrent
                      : item.reached
                        ? styles.stageItemReached
                        : styles.stageItem
                  }
                  data-stage-phase={item.phase}
                  data-stage-current={item.current ? "true" : "false"}
                >
                  {item.label}
                </span>
              </span>
            ))}
          </span>
        ) : null}
      </div>
    </div>
  );
}
