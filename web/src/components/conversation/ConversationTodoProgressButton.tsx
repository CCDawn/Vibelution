import { CircleCheck, CirclePause, ListChecks, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import { VButton, VPopover } from "../vui";
import { ConversationTodoChecklist } from "./ConversationTodoChecklist";
import type { SessionTodoChecklistProjection } from "./conversationTodoChecklistModel";
import styles from "./ConversationTodoProgressButton.styles";

export type ConversationTodoProgressButtonProps = {
  plan: SessionTodoChecklistProjection;
  lang: "zh" | "en";
};

/** Independent anchored checklist; journal projection only, no rail state. */
export function ConversationTodoProgressButton({
  plan,
  lang,
}: ConversationTodoProgressButtonProps) {
  const [expanded, setExpanded] = useState(false);
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
    <VPopover
      open={expanded}
      onOpenChange={setExpanded}
      align="end"
      side="bottom"
      sideOffset={8}
      aria-label={copy.todoChecklistTitle}
      contentClassName={styles.popover}
      data-vui="conversation-todo-popover"
      trigger={(
        <VButton
          type="button"
          variant="ghost"
          density="compact"
          className={styles.button}
          icon={<Icon size={14} aria-hidden="true" className={status === "running" ? styles.runningIcon : undefined} />}
          aria-label={label}
          title={status === "running" && currentItem ? `${label} · ${currentItem.activeForm}` : label}
          data-testid="conversation-todo-progress"
          data-todo-progress-status={status}
        >
          {copy.todoProgressTitle} <span>{counter}</span>
          {status === "paused" ? <span className={styles.pausedLabel}>{statusLabel}</span> : null}
        </VButton>
      )}
    >
      <ConversationTodoChecklist
        snapshot={snapshot}
        lang={lang}
        turnSettled={turnSettled}
        presentation="panel"
      />
    </VPopover>
  );
}
