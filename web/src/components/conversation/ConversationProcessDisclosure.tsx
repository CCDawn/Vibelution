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
  codexTranscriptToolRawName,
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
  messageOrder?: ReadonlyMap<string, number>;
  onUserToggle?: ConversationProcessUserToggle;
};

const PROCESS_ROW_STAGGER_MS = 28;
const PROCESS_ROW_STAGGER_LIMIT = 6;

function canonicalCellOrder(
  cell: CodexTranscriptCell,
  fallbackIndex: number,
  messageOrder?: ReadonlyMap<string, number>,
) {
  const projectedMessageOrder = messageOrder?.get(cell.messageId);
  const sequence = cell.toolLifecycleModel?.toolCalls
    .map((toolCall) => toolCall.sequence)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    .at(-1);
  return {
    message: projectedMessageOrder ?? fallbackIndex,
    sequence: sequence ?? fallbackIndex,
    fallback: fallbackIndex,
  };
}

function cellOccursAfter(
  candidate: ReturnType<typeof canonicalCellOrder>,
  failed: ReturnType<typeof canonicalCellOrder>,
) {
  if (candidate.message !== failed.message) {
    return candidate.message > failed.message;
  }
  if (candidate.sequence !== failed.sequence) {
    return candidate.sequence > failed.sequence;
  }
  return candidate.fallback > failed.fallback;
}

function unrecoveredFailedCells(
  cells: readonly CodexTranscriptCell[],
  messageOrder?: ReadonlyMap<string, number>,
) {
  return cells.filter((cell, index) => {
    if (cell.status !== "failed") {
      return false;
    }
    const toolIdentity = codexTranscriptToolRawName(cell) || String(cell.title || "").trim();
    if (!toolIdentity) {
      return true;
    }
    const failedOrder = canonicalCellOrder(cell, index, messageOrder);
    return !cells.some((candidate, candidateIndex) => {
      if (
        candidate.status !== "completed"
        || (codexTranscriptToolRawName(candidate) || String(candidate.title || "").trim()) !== toolIdentity
      ) {
        return false;
      }
      return cellOccursAfter(
        canonicalCellOrder(candidate, candidateIndex, messageOrder),
        failedOrder,
      );
    });
  });
}

export function processState(
  cells: readonly CodexTranscriptCell[],
  messageOrder?: ReadonlyMap<string, number>,
) {
  // Prefer unrecovered failures over stale "running" so timeout/fail settle the summary.
  if (unrecoveredFailedCells(cells, messageOrder).length > 0) {
    const stillRunning = cells.some((cell) => {
      if (cell.status !== "running" && cell.status !== "pending") {
        return false;
      }
      // Timed-out rows may briefly keep a running status while summary already says 超时.
      const haystack = `${cell.summary || ""} ${cell.title || ""}`;
      return !/超时|timed?\s*out/i.test(haystack);
    });
    if (!stillRunning) {
      return "failed";
    }
  }
  if (cells.some((cell) => {
    if (cell.status !== "running" && cell.status !== "pending") {
      return false;
    }
    const haystack = `${cell.summary || ""} ${cell.title || ""}`;
    return !/超时|timed?\s*out/i.test(haystack);
  })) {
    return "running";
  }
  if (unrecoveredFailedCells(cells, messageOrder).length > 0) {
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

function firstFailedToolIdentity(
  cells: readonly CodexTranscriptCell[],
  messageOrder?: ReadonlyMap<string, number>,
) {
  const failed = unrecoveredFailedCells(cells, messageOrder)[0];
  if (!failed) {
    return "";
  }
  // The expanded transcript row owns failure details. Keep the collapsed
  // summary identifiable without repeating its full error message.
  return codexTranscriptToolRawName(failed) || String(failed.title || "").trim();
}

export function processLabel(
  cells: readonly CodexTranscriptCell[],
  language: "zh" | "en",
  messageOrder?: ReadonlyMap<string, number>,
) {
  const state = processState(cells, messageOrder);
  const labels = language === "zh"
    ? { completed: "已处理", failed: "工具失败", running: "处理中" }
    : { completed: "Processed", failed: "Tool failed", running: "Processing" };
  const duration = processDuration(cells);
  // Codex: "已处理 18m 3s" — keep status + duration adjacent without middle-dot.
  const parts = [
    labels[state],
    duration === null ? "" : formatCodexTranscriptDuration(duration),
  ];
  if (state === "failed") {
    const toolIdentity = firstFailedToolIdentity(cells, messageOrder);
    if (toolIdentity) {
      parts.push(language === "zh" ? `· ${toolIdentity}` : `· ${toolIdentity}`);
    } else {
      parts.push(language === "zh" ? "· 展开查看原因" : "· expand for details");
    }
  } else if (state === "completed" && cells.length >= 3) {
    // Hint that the disclosure holds a multi-step tool trail.
    parts.push(language === "zh" ? `· ${cells.length} 步` : `· ${cells.length} steps`);
  }
  return parts.filter(Boolean).join(" ");
}

export function ConversationProcessDisclosure({
  cells,
  language,
  children,
  messageOrder,
  onUserToggle,
}: ConversationProcessDisclosureProps) {
  const state = processState(cells, messageOrder);
  const running = state === "running";
  const {
    expanded,
    handleContentTransitionEnd,
    handleSummaryClick,
    mounted,
  } = useConversationProcessDisclosureMotion(running, onUserToggle);
  const contentId = useId();
  const label = processLabel(cells, language, messageOrder);
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
      data-codex-process-state={state}
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
