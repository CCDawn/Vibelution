import { CircleCheck, CirclePause, ListChecks, LoaderCircle } from "lucide-react";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import { VButton } from "../vui";
import type { SessionTodoChecklistProjection } from "./conversationTodoChecklistModel";
import styles from "./ConversationTodoProgressButton.styles";

export type ConversationTodoProgressButtonProps = {
  plan: SessionTodoChecklistProjection;
  lang: "zh" | "en";
  expanded: boolean;
  onPress: () => void;
};

/** Compact entry into the existing session plan rail; journal projection only. */
export function ConversationTodoProgressButton({
  plan,
  lang,
  expanded,
  onPress,
}: ConversationTodoProgressButtonProps) {
  const { snapshot, turnSettled } = plan;
  const copy = dictionaryChat[lang];
  const currentItem = snapshot.items.find((item) => item.status === "in_progress");
  const status = !snapshot.hasUnfinished
    ? "completed"
    : turnSettled ? "paused" : currentItem ? "running" : "pending";
  const statusLabel = status === "completed" ? copy.todoProgressCompleted
    : status === "paused" ? copy.todoProgressPaused
      : status === "running" ? copy.todoProgressRunning : copy.todoProgressPending;
  const counter = `${snapshot.completedCount}/${snapshot.total}`;
  const label = `${copy.todoChecklistTitle} ${counter} · ${statusLabel}`;
  const Icon = status === "completed" ? CircleCheck
    : status === "paused" ? CirclePause
      : status === "running" ? LoaderCircle : ListChecks;

  return (
    <VButton
      type="button"
      variant="ghost"
      density="compact"
      className={styles.button}
      icon={<Icon size={14} aria-hidden="true" className={status === "running" ? styles.runningIcon : undefined} />}
      aria-label={label}
      aria-expanded={expanded}
      aria-controls="chat-status-pane"
      tooltip={status === "running" && currentItem ? `${label} · ${currentItem.activeForm}` : label}
      data-testid="conversation-todo-progress"
      data-todo-progress-status={status}
      onPress={onPress}
    >
      {copy.todoProgressTitle} <span>{counter}</span>
      {status === "paused" ? <span className={styles.pausedLabel}>{statusLabel}</span> : null}
    </VButton>
  );
}
