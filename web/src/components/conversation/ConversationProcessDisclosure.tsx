import { ChevronRight } from "lucide-react";
import React, {
  Children,
  type CSSProperties,
  type ReactNode,
  useId,
} from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  formatCodexTranscriptDuration,
} from "./conversationToolActivityModel";
import styles from "./ConversationProcessDisclosure.styles";
import {
  type ConversationProcessUserToggle,
  useConversationProcessDisclosureMotion,
} from "./useConversationProcessDisclosureMotion";

type ConversationProcessDisclosureProps = {
  cells: readonly CodexTranscriptCell[];
  language: "zh" | "en";
  children: ReactNode;
  onUserToggle?: ConversationProcessUserToggle;
};

const PROCESS_ROW_STAGGER_MS = 28;
const PROCESS_ROW_STAGGER_LIMIT = 6;

function processState(cells: readonly CodexTranscriptCell[]) {
  if (cells.some((cell) => cell.status === "running" || cell.status === "pending")) {
    return "running";
  }
  if (cells.some((cell) => cell.status === "failed")) {
    return "failed";
  }
  return "completed";
}

function processDuration(cells: readonly CodexTranscriptCell[]) {
  const durations = cells
    .map(codexTranscriptToolDurationSeconds)
    .filter((duration): duration is number => duration !== null);
  if (durations.length === 0) {
    return null;
  }
  return durations.reduce((total, duration) => total + duration, 0);
}

function processLabel(cells: readonly CodexTranscriptCell[], language: "zh" | "en") {
  const state = processState(cells);
  const labels = language === "zh"
    ? { completed: "已处理", failed: "处理已停止", running: "处理中" }
    : { completed: "Processed", failed: "Processing stopped", running: "Processing" };
  const duration = processDuration(cells);
  return [
    labels[state],
    duration === null ? "" : formatCodexTranscriptDuration(duration),
  ].filter(Boolean).join(" ");
}

export function ConversationProcessDisclosure({
  cells,
  language,
  children,
  onUserToggle,
}: ConversationProcessDisclosureProps) {
  const running = processState(cells) === "running";
  const {
    expanded,
    handleContentTransitionEnd,
    handleSummaryClick,
    mounted,
  } = useConversationProcessDisclosureMotion(running, onUserToggle);
  const contentId = useId();
  const label = processLabel(cells, language);
  const toggleLabel = language === "zh"
    ? "展开或收起处理记录"
    : "Expand or collapse process details";
  // Static transcript audits run through server rendering, while the product is
  // a client-only Vite surface. Keep SSR evidence complete without retaining
  // the collapsed tool subtree in the interactive browser.
  const shouldRenderContent = mounted || typeof window === "undefined";
  const rows = shouldRenderContent ? Children.toArray(children) : [];

  return (
    <details
      className={styles.disclosure}
      data-codex-process-disclosure="true"
      data-codex-process-state={processState(cells)}
      data-codex-process-expanded={expanded ? "true" : "false"}
      aria-live={running ? "polite" : undefined}
      open={mounted}
    >
      <summary
        className={styles.summary}
        aria-controls={contentId}
        aria-expanded={expanded}
        aria-label={toggleLabel}
        onClick={handleSummaryClick}
      >
        <span>{label}</span>
        <ChevronRight
          className={[styles.chevron, expanded ? styles.chevronExpanded : ""].filter(Boolean).join(" ")}
          size={14}
          aria-hidden="true"
        />
      </summary>
      {shouldRenderContent ? (
        <div
          id={contentId}
          className={[
            styles.contentMotion,
            expanded ? styles.contentMotionExpanded : styles.contentMotionCollapsed,
          ].join(" ")}
          aria-hidden={!expanded}
          onTransitionEnd={handleContentTransitionEnd}
        >
          <div className={styles.contentClip}>
            <div className={styles.content}>
              {rows.map((row, index) => (
                <div
                  // Transcript nodes already carry stable keys; Children.toArray preserves them.
                  key={(row as React.ReactElement).key ?? index}
                  className={[
                    styles.row,
                    expanded ? styles.rowExpanded : styles.rowCollapsed,
                  ].join(" ")}
                  // Bounded animation exception: the delay depends on the rendered row index.
                  style={{
                    transitionDelay: expanded
                      ? `${Math.min(index, PROCESS_ROW_STAGGER_LIMIT) * PROCESS_ROW_STAGGER_MS}ms`
                      : "0ms",
                  } as CSSProperties}
                >
                  {row}
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </details>
  );
}
