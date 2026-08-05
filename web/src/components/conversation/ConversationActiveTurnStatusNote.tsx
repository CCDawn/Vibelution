import { LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import {
  activeTurnElapsedSeconds,
  activeTurnStageBarPhaseLabel,
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
 * Compact active-turn status: one heartbeat line + optional silent stage dots.
 * Full phase labels stay in aria; UI no longer repeats 发送→准备→请求→思考.
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
  const currentPhaseLabel = stageBarItems.find((item) => item.current)?.label
    || activeTurnStageBarPhaseLabel("thinking", lang);
  const stageBarAria = stageBarItems.length > 0
    ? stageBarItems
      .map((item) => {
        const mark = item.current ? (lang === "en" ? "current" : "当前") : (item.reached ? "✓" : "·");
        return `${item.label}${item.current || item.reached ? ` (${mark})` : ""}`;
      })
      .join(lang === "en" ? " → " : " → ")
    : "";

  return (
    <div
      className={styles.note}
      role="status"
      aria-live="polite"
      aria-label={[resolvedStatusLabel, heartbeatText, stageBarAria].filter(Boolean).join(" · ")}
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
          <span
            className={styles.stageBar}
            title={stageBarAria || currentPhaseLabel}
            aria-hidden="true"
          >
            {stageBarItems.map((item) => (
              <span
                key={item.phase}
                className={styles.stageBarItem}
                data-stage-phase={item.phase}
                data-stage-current={item.current ? "true" : "false"}
              >
                <span
                  className={
                    item.current
                      ? styles.stageDotCurrent
                      : item.reached
                        ? styles.stageDotReached
                        : styles.stageDot
                  }
                />
              </span>
            ))}
          </span>
        ) : null}
      </div>
    </div>
  );
}
