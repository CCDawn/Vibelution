import { Check, Circle, CircleDot } from "lucide-react";

import type {
  ConversationToolChecklistItemStatus,
  ConversationToolChecklistModel,
} from "./conversationToolChecklistModel";
import type { ConversationToolPresentationLanguage } from "./conversationToolPresentation";
import styles from "./ConversationToolChecklist.styles";

type ConversationToolChecklistProps = {
  model: ConversationToolChecklistModel;
  language: ConversationToolPresentationLanguage;
};

function itemStatusLabel(
  status: ConversationToolChecklistItemStatus,
  language: ConversationToolPresentationLanguage,
) {
  if (status === "completed") {
    return language === "zh" ? "已完成" : "Completed";
  }
  if (status === "in_progress") {
    return language === "zh" ? "进行中" : "In progress";
  }
  return language === "zh" ? "待处理" : "Pending";
}

function itemStatusIcon(status: ConversationToolChecklistItemStatus) {
  if (status === "completed") {
    return <Check size={12} strokeWidth={2.5} aria-hidden="true" />;
  }
  if (status === "in_progress") {
    return <CircleDot size={12} aria-hidden="true" />;
  }
  return <Circle size={12} aria-hidden="true" />;
}

function progressLabel(model: ConversationToolChecklistModel, language: ConversationToolPresentationLanguage) {
  if (model.items.length === 0) {
    return "";
  }
  return language === "zh"
    ? `${model.completedCount}/${model.items.length} 已完成`
    : `${model.completedCount}/${model.items.length} done`;
}

/**
 * Inline checklist for task/plan tool calls. The tool call's canonical input is
 * already a step list with status, so the timeline shows the checklist itself
 * instead of a generic tool row plus raw JSON.
 */
export function ConversationToolChecklist({ model, language }: ConversationToolChecklistProps) {
  return (
    <div
      className={styles.root}
      data-codex-tool-checklist="true"
      data-codex-tool-checklist-tool={model.toolName}
      data-conversation-part-key={model.cellId}
    >
      <div className={styles.header}>
        <span className={styles.title}>{model.title}</span>
        <span className={styles.progress}>{progressLabel(model, language)}</span>
        {model.explanation ? (
          <span className={styles.explanation}>{model.explanation}</span>
        ) : null}
      </div>
      <ul className={styles.items}>
        {model.items.map((item) => (
          <li
            key={item.id}
            className={styles.item}
            data-codex-tool-checklist-item="true"
            data-checklist-item-status={item.status}
          >
            <span className={`${styles.marker} ${styles[`marker_${item.status}`]}`}>
              {itemStatusIcon(item.status)}
            </span>
            <span className={`${styles.label} ${styles[`label_${item.status}`]}`}>
              {item.label}
              <span className="sr-only">{` · ${itemStatusLabel(item.status, language)}`}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
