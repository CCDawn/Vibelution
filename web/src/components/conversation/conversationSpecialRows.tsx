import type { ReactNode } from "react";
import { ChevronsDownUp, RefreshCw, TerminalSquare } from "lucide-react";

import type { ConversationMessage } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import {
  isCliAgentLifecycleMessage,
  isContextCompressionMarkerMessage,
  isSessionRecoveryResumedMessage,
} from "./conversationMessagePredicates";
import {
  cliAgentLifecycleDetail,
  cliAgentLifecycleLabel,
  sessionRecoveryResumedDetail,
  sessionRecoveryResumedLabel,
} from "./conversationSpecialMessagePresentation";
import styles from "./ConversationView.styles";

/** Presentation tone of a context-compression checkpoint divider. */
export type ConversationCompressionDividerTone =
  | "applied"
  | "skipped_low_savings"
  | "failed_preserved";

/**
 * Backend compression statuses spell both ways ("applied" from the ledger
 * projection, "context_compression_applied" from status turn items); normalize
 * to one divider tone. Unknown statuses present as the plain applied row.
 */
function normalizeCompressionDividerTone(raw: unknown): ConversationCompressionDividerTone {
  const value = String(raw ?? "").trim().toLowerCase().replace(/^context_compression_/, "");
  if (value === "skipped_low_savings") {
    return "skipped_low_savings";
  }
  if (value === "failed_preserved") {
    return "failed_preserved";
  }
  return "applied";
}

/**
 * Compression checkpoints reach the timeline through two carriers: server
 * projections with `metadata.kind = "context_compression_marker"` and status
 * turn items whose diagnosticSummary carries the same kind (the native Codex
 * transcript shape). Both render as one ZCode-style hairline divider instead
 * of a generic status cell; the token-saving text never renders.
 */
export function conversationCompressionDividerTone(
  message: ConversationMessage,
): ConversationCompressionDividerTone | null {
  if (isContextCompressionMarkerMessage(message)) {
    return normalizeCompressionDividerTone(message.metadata?.status);
  }
  if (message.role !== "assistant") {
    return null;
  }
  for (const item of message.turnItems) {
    if (item.type !== "status") {
      continue;
    }
    const summary = item.diagnosticSummary;
    if (summary && String(summary.kind ?? "").trim() === "context_compression_marker") {
      return normalizeCompressionDividerTone(summary.status ?? item.code);
    }
  }
  return null;
}

export type ConversationSpecialRowsDeps = {
  lang: "zh" | "en";
  t: (key: TranslationKey) => string;
  formatTimestamp: (timestamp: string) => string;
};

/**
 * Whole-row timeline specials that replace the agent turn body: CLI agent
 * lifecycle notes, session-recovery rows and compression checkpoint dividers.
 * Extracted from ConversationView with identical output.
 */
export function createConversationSpecialRows({
  lang,
  t,
  formatTimestamp,
}: ConversationSpecialRowsDeps) {
  /** Returns the special row for the message, or null when it renders as a normal turn. */
  function renderTimelineSpecialRow(message: ConversationMessage, rowKey: string): ReactNode {
    if (isCliAgentLifecycleMessage(message)) {
      const detail = cliAgentLifecycleDetail(message);
      return (
        <article
          key={rowKey}
          className={styles.cliAgentLifecycleTurn}
          data-conversation-row-key={rowKey}
        >
          <span className={styles.cliAgentLifecycleIcon} aria-hidden="true">
            <TerminalSquare size={14} />
          </span>
          <span className={styles.cliAgentLifecycleText}>
            {cliAgentLifecycleLabel(message, lang)}
          </span>
          {detail ? <code className={styles.cliAgentLifecycleMeta}>{detail}</code> : null}
          {message.timestamp ? (
            <span className={styles.cliAgentLifecycleTime}>{formatTimestamp(message.timestamp)}</span>
          ) : null}
        </article>
      );
    }
    if (isSessionRecoveryResumedMessage(message)) {
      const detail = sessionRecoveryResumedDetail(message, lang);
      return (
        <article
          key={rowKey}
          className={styles.cliAgentLifecycleTurn}
          data-conversation-row-key={rowKey}
        >
          <span className={styles.cliAgentLifecycleIcon} aria-hidden="true">
            <RefreshCw size={14} />
          </span>
          <span className={styles.cliAgentLifecycleText}>
            {sessionRecoveryResumedLabel(message, lang)}
          </span>
          {detail ? <code className={styles.cliAgentLifecycleMeta}>{detail}</code> : null}
          {message.timestamp ? (
            <span className={styles.cliAgentLifecycleTime}>{formatTimestamp(message.timestamp)}</span>
          ) : null}
        </article>
      );
    }
    // Context-compression checkpoints are timeline chrome, not model
    // answers: one hairline divider per checkpoint, toned by outcome.
    // The token-saving numbers never render.
    const compressionTone = conversationCompressionDividerTone(message);
    if (compressionTone) {
      const compressionLabel = compressionTone === "applied"
        ? t("compressionDividerApplied")
        : compressionTone === "skipped_low_savings"
          ? t("compressionDividerSkipped")
          : t("compressionDividerFailed");
      return (
        <article
          key={rowKey}
          className={[
            styles.turnDividerRow,
            compressionTone === "applied"
              ? styles.turnDividerToneApplied
              : compressionTone === "skipped_low_savings"
                ? styles.turnDividerToneQuiet
                : styles.turnDividerToneWarning,
          ].filter(Boolean).join(" ")}
          data-conversation-row-key={rowKey}
          data-conversation-compression-divider={compressionTone}
        >
          <span className={styles.turnDividerRule} aria-hidden="true" />
          <span className={styles.turnDividerIcon} aria-hidden="true">
            <ChevronsDownUp size={13} />
          </span>
          <span className={styles.turnDividerLabel}>{compressionLabel}</span>
          <span className={styles.turnDividerRule} aria-hidden="true" />
        </article>
      );
    }
    return null;
  }

  return { renderTimelineSpecialRow };
}
