import type { ReactNode } from "react";

import type {
  CodexToolActivityPillStatusKind,
  CodexToolActivityPills,
} from "./conversationToolPresentation";
import styles from "./ConversationToolActivity.styles";

/**
 * Status kinds that need an explicit trailing label. Running/completed rely on
 * the leading icon only — matching Codex's quiet tool rail (no dual chips).
 */
const SHOW_STATUS_LABEL: ReadonlySet<CodexToolActivityPillStatusKind> = new Set([
  "failed",
  "timeout",
  "attention",
]);

export function toolActivityAriaTitle(pills: CodexToolActivityPills) {
  const parts = [pills.actionLabel];
  if (pills.statusLabel && pills.statusKind !== "completed") {
    parts.push(pills.statusLabel);
  }
  if (pills.subject) parts.push(pills.subject);
  if (pills.durationLabel) parts.push(pills.durationLabel);
  return parts.join(" ");
}

/**
 * Shared Codex-style tool row chrome used by the native tool rail and the
 * legacy agent-message timeline.
 *
 * Visual contract (Codex-aligned):
 * - leading icon carries running/done/failed state
 * - action is plain text (not a rounded chip)
 * - status text only for failures / attention (not "运行中"/"执行完成" chips)
 * - subject + duration stay muted
 */
export function ConversationToolActivityPills({
  pills,
  leadingIcon = null,
  className = "",
}: {
  pills: CodexToolActivityPills;
  leadingIcon?: ReactNode;
  className?: string;
}) {
  const showStatusLabel = SHOW_STATUS_LABEL.has(pills.statusKind) && Boolean(pills.statusLabel);

  return (
    <>
      {leadingIcon}
      <span
        className={`${styles.itemBody}${className ? ` ${className}` : ""}`}
        data-codex-tool-row="true"
        data-codex-tool-status-kind={pills.statusKind}
      >
        <span className={styles.actionLabel} data-codex-tool-action-pill="true">
          {pills.actionLabel}
        </span>
        {showStatusLabel ? (
          <span
            className={`${styles.statusLabel} ${styles[`statusLabel_${pills.statusKind}` as keyof typeof styles] || ""}`}
            data-codex-tool-status-pill="true"
            data-codex-tool-status-kind={pills.statusKind}
          >
            {pills.statusLabel}
          </span>
        ) : null}
        {pills.subject ? (
          <span className={styles.itemPreview} title={pills.subject} data-codex-tool-subject="true">
            {pills.subject}
          </span>
        ) : null}
        {pills.durationLabel ? (
          <span className={styles.itemDuration} data-codex-tool-duration="true">
            {pills.durationLabel}
          </span>
        ) : null}
      </span>
    </>
  );
}
