import { LoaderCircle } from "lucide-react";
import type { ReactNode } from "react";

import type {
  CodexToolActivityPillStatusKind,
  CodexToolActivityPills,
} from "./conversationToolPresentation";
import styles from "./ConversationToolActivity.styles";

const STATUS_PILL_CLASS: Record<CodexToolActivityPillStatusKind, string> = {
  running: styles.statusPill_running,
  completed: styles.statusPill_completed,
  failed: styles.statusPill_failed,
  timeout: styles.statusPill_timeout,
  attention: styles.statusPill_attention,
  idle: styles.statusPill_idle,
};

export function toolActivityAriaTitle(pills: CodexToolActivityPills) {
  const parts = [pills.actionLabel, pills.statusLabel];
  if (pills.subject) parts.push(pills.subject);
  if (pills.durationLabel) parts.push(pills.durationLabel);
  return parts.join(" ");
}

/**
 * Shared Codex-style action|status pill chrome used by both the native tool rail
 * and the legacy agent-message operation timeline so tool rows render one way.
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
  return (
    <>
      {leadingIcon}
      <span className={`${styles.itemBody}${className ? ` ${className}` : ""}`}>
        <span className={styles.actionPill} data-codex-tool-action-pill="true">
          {pills.actionLabel}
        </span>
        <span
          className={`${styles.statusPill} ${STATUS_PILL_CLASS[pills.statusKind]}`}
          data-codex-tool-status-pill="true"
          data-codex-tool-status-kind={pills.statusKind}
        >
          {pills.statusKind === "running" ? (
            <LoaderCircle className="animate-spin" size={12} aria-hidden="true" />
          ) : null}
          {pills.statusLabel}
        </span>
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
