import type { CSSProperties, ReactNode } from "react";

import { VTooltip } from "../vui";
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
  if (pills.diffStatLabel) parts.push(pills.diffStatLabel);
  if (pills.durationLabel) parts.push(pills.durationLabel);
  return parts.join(" ");
}

/**
 * Shared Codex-style tool row chrome used by the native tool rail and the
 * legacy agent-message timeline.
 *
 * Visual contract (Codex/ZCode-aligned):
 * - leading icon is always static; running lives in the action word's shimmer
 * - action is plain text (not a rounded chip)
 * - status text only for failures / attention (not "运行中"/"执行完成" chips);
 *   the colored word + dashed underline carries failure semantics, hovering it
 *   reveals the error summary (statusTooltip) instead of a red card blast
 * - subject + duration stay muted
 */
export function ConversationToolActivityPills({
  pills,
  leadingIcon = null,
  className = "",
  statusTooltip,
  agentAccentStyle = null,
}: {
  pills: CodexToolActivityPills;
  leadingIcon?: ReactNode;
  className?: string;
  /** Error summary revealed on hover of the status word (VTooltip). */
  statusTooltip?: string;
  /**
   * ZCode subagent-name coloring: when the row's subject IS the agent name,
   * the caller resolves its stable color bucket and passes the
   * `--subagent-accent` custom-property payload here; the name renders as a
   * token-derived tinted chip. Absent → unchanged muted subject.
   */
  agentAccentStyle?: Record<string, string> | null;
}) {
  const showStatusLabel = SHOW_STATUS_LABEL.has(pills.statusKind) && Boolean(pills.statusLabel);
  const running = pills.statusKind === "running";
  const coloredAgentName = Boolean(agentAccentStyle && pills.subject);

  return (
    <>
      {leadingIcon}
      <span
        className={`${styles.itemBody}${className ? ` ${className}` : ""}`}
        data-codex-tool-row="true"
        data-codex-tool-status-kind={pills.statusKind}
      >
        <span
          className={running ? `${styles.actionLabel} ${styles.actionLabelRunning}` : styles.actionLabel}
          data-codex-tool-action-pill="true"
          data-codex-tool-action-running={running ? "true" : undefined}
        >
          {pills.actionLabel}
        </span>
        {showStatusLabel ? (
          statusTooltip ? (
            <VTooltip width="compact" content={statusTooltip}>
              <span
                className={`${styles.statusLabel} ${styles[`statusLabel_${pills.statusKind}` as keyof typeof styles] || ""}`}
                data-codex-tool-status-pill="true"
                data-codex-tool-status-kind={pills.statusKind}
              >
                {pills.statusLabel}
              </span>
            </VTooltip>
          ) : (
            <span
              className={`${styles.statusLabel} ${styles[`statusLabel_${pills.statusKind}` as keyof typeof styles] || ""}`}
              data-codex-tool-status-pill="true"
              data-codex-tool-status-kind={pills.statusKind}
            >
              {pills.statusLabel}
            </span>
          )
        ) : null}
        {pills.subject ? (
          <span className={styles.itemPreview} title={pills.subject} data-codex-tool-subject="true">
            {coloredAgentName ? (
              <span
                className={styles.agentNameChip}
                style={agentAccentStyle as CSSProperties}
                data-codex-tool-agent-name="true"
              >
                {pills.subject}
              </span>
            ) : (
              pills.subject
            )}
          </span>
        ) : null}
        {pills.diffStatLabel ? (
          // Kept out of the truncating subject so an edit's size survives a long path.
          <span className={styles.diffStatLabel} data-codex-tool-diff-stat="true">
            {pills.diffStatLabel}
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
