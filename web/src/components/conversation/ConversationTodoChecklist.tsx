import { ChevronDown, ChevronRight, Circle, CircleCheck, LoaderCircle, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { VNativeButton } from "../vui";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import type { TodoChecklistSnapshot } from "./conversationTodoChecklistModel";
import styles from "./ConversationTodoChecklist.styles";

export type ConversationTodoChecklistProps = {
  snapshot: TodoChecklistSnapshot;
  lang: "zh" | "en" | string;
  /** Settled (history) turns render read-only and collapsed by default. */
  turnSettled: boolean;
};

/**
 * Turn-scoped todo checklist card (Claude Code TodoWrite paradigm): one row
 * per item — completed check, in-progress activeForm with spinner, pending
 * hollow circle — plus a completion counter. When the turn settles with
 * unfinished items, a visible warning line flags the gap (presentation only;
 * it never blocks or alters turn state).
 */
export function ConversationTodoChecklist({
  snapshot,
  lang,
  turnSettled,
}: ConversationTodoChecklistProps) {
  const langKey = lang === "en" ? "en" : "zh";
  const [expanded, setExpanded] = useState(!turnSettled);
  const copy = dictionaryChat[langKey];
  const counter = `${snapshot.completedCount}/${snapshot.total}`;
  const showWarning = turnSettled && snapshot.hasUnfinished;
  const header = (
    <VNativeButton
      type="button"
      className={styles.header}
      onClick={() => setExpanded((current) => !current)}
      aria-expanded={expanded}
      data-testid="todo-checklist-toggle"
    >
      {expanded ? (
        <ChevronDown className={styles.chevron} size={14} aria-hidden="true" />
      ) : (
        <ChevronRight className={styles.chevron} size={14} aria-hidden="true" />
      )}
      <span className={styles.title}>{copy.todoChecklistTitle}</span>
      <span className={styles.counter} data-testid="todo-checklist-counter">{counter}</span>
    </VNativeButton>
  );
  return (
    <div
      className={styles.card}
      role="group"
      aria-label={copy.todoChecklistTitle}
      data-todo-checklist-settled={turnSettled ? "true" : undefined}
      data-todo-checklist-unfinished={snapshot.hasUnfinished ? "true" : undefined}
    >
      {header}
      {showWarning ? (
        <p className={styles.warning} data-testid="todo-checklist-warning">
          <TriangleAlert size={13} aria-hidden="true" />
          <span>{copy.todoChecklistUnfinishedWarning}</span>
        </p>
      ) : null}
      {expanded ? (
        <ul className={styles.list} data-testid="todo-checklist-items">
          {snapshot.items.map((item, index) => (
            <li
              key={`${index}-${item.content}`}
              className={[
                styles.item,
                item.status === "completed" ? styles.itemCompleted : "",
                item.status === "in_progress" ? styles.itemActive : "",
              ].filter(Boolean).join(" ")}
              data-todo-status={item.status}
            >
              {item.status === "completed" ? (
                <CircleCheck className={styles.checkIcon} size={14} aria-hidden="true" />
              ) : item.status === "in_progress" ? (
                <LoaderCircle className={styles.spinnerIcon} size={14} aria-hidden="true" />
              ) : (
                <Circle className={styles.pendingIcon} size={14} aria-hidden="true" />
              )}
              <span className={styles.itemText}>
                {item.status === "in_progress" ? item.activeForm : item.content}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
