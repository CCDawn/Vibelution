import { ChevronRight } from "lucide-react";
import React, {
  Children,
  type CSSProperties,
  type ReactNode,
  useId,
  useEffect,
  useRef,
} from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  codexTranscriptToolDurationSeconds,
  codexTranscriptToolRawName,
  formatCodexTranscriptDuration,
} from "./conversationToolActivityModel";
import {
  formatConversationTurnWorkBreakdown,
  formatConversationTurnWorkDuration,
  type ConversationTurnWorkSummary,
} from "./conversationTurnWorkStatus";
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
  /**
   * True while the owning assistant turn is still streaming. Multi-step agents
   * often finish every current tool before the next model step; without this
   * the process rail collapses to "已处理" mid-turn and hides the trail.
   */
  turnStreaming?: boolean;
  /**
   * Settled-turn work summary (ZCode AssistantHistoryStatus parity): supplies
   * the authoritative worked time and lets the same trigger degrade to 「已处理」
   * when no duration is derivable.
   */
  workSummary?: ConversationTurnWorkSummary | null;
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

function isRetryCell(cell: CodexTranscriptCell) {
  const content = [
    cell.title,
    cell.summary,
    cell.text,
  ].map((value) => String(value ?? "").trim().toLowerCase()).filter(Boolean).join(" ");
  return Boolean(
    content.includes("model_retry")
    || content.includes("retrying")
    || content.includes("模型连接正在重试")
    || content.includes("模型请求重试")
    || content.includes("请求重试")
  );
}

export function processLabel(
  cells: readonly CodexTranscriptCell[],
  language: "zh" | "en",
  messageOrder?: ReadonlyMap<string, number>,
  turnStreaming = false,
  workSummary?: ConversationTurnWorkSummary | null,
) {
  const state = processState(cells, messageOrder, turnStreaming);
  const labels = language === "zh"
    ? {
      completed: "已处理",
      completedWithDuration: "已工作",
      failed: "工具失败",
      running: "处理中",
      runningWithDuration: "工作中",
    }
    : {
      completed: "Processed",
      completedWithDuration: "Worked for",
      failed: "Tool failed",
      running: "Processing",
      runningWithDuration: "Working for",
    };
  const duration = processDuration(cells);
  // Turn-level worked time outranks the tool-duration sum: it is the fact the
  // backend measured, and it is what makes 「已工作」 possible at all.
  const durationLabel = workSummary
    ? formatConversationTurnWorkDuration(workSummary.durationMs, language)
    : (duration === null ? "" : formatCodexTranscriptDuration(duration));
  // Codex shows model retries only as a live status heartbeat; the settled
  // process summary never carries a retry row or a retry note.
  const retryFreeCells = cells.filter((cell) => !isRetryCell(cell));
  const traceLength = retryFreeCells.length;
  const headline = durationLabel
    ? state === "completed"
      ? labels.completedWithDuration
      : state === "running"
        ? labels.runningWithDuration
        : labels.failed
    : labels[state];
  const parts = [headline, durationLabel];
  if (state === "failed") {
    const toolIdentity = firstFailedToolIdentity(retryFreeCells, messageOrder);
    if (toolIdentity) {
      parts.push(language === "zh" ? `· ${toolIdentity}` : `· ${toolIdentity}`);
    } else {
      parts.push(language === "zh" ? "· 展开查看原因" : "· expand for details");
    }
  } else if (traceLength >= 3) {
    // Hint that the disclosure holds a multi-step tool trail (including mid-turn).
    parts.push(language === "zh" ? `· ${traceLength} 步` : `· ${traceLength} steps`);
  }
  return parts.filter(Boolean).join(" ");
}

/**
 * Process rail state for the disclosure summary.
 * When the turn is still streaming, keep "running" even if every current tool
 * cell already settled — otherwise multi-step agents collapse the trail between batches.
 */
export function processState(
  cells: readonly CodexTranscriptCell[],
  messageOrder?: ReadonlyMap<string, number>,
  turnStreaming = false,
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
    if (!stillRunning && !turnStreaming) {
      return "failed";
    }
  }
  if (turnStreaming) {
    return "running";
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

export function ConversationProcessDisclosure({
  cells,
  language,
  children,
  messageOrder,
  onUserToggle,
  turnStreaming = false,
  workSummary = null,
}: ConversationProcessDisclosureProps) {
  const state = processState(cells, messageOrder, turnStreaming);
  const running = state === "running";
  const {
    expanded,
    handleContentTransitionEnd,
    handleSummaryClick,
    mounted,
  } = useConversationProcessDisclosureMotion(running, onUserToggle);
  const contentId = useId();
  const contentRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!expanded && contentRef.current?.contains(document.activeElement)) {
      summaryRef.current?.focus({ preventScroll: true });
    }
  }, [expanded]);
  const label = processLabel(cells, language, messageOrder, turnStreaming, workSummary);
  const toggleLabel = language === "zh"
    ? "展开或收起处理记录"
    : "Expand or collapse process details";
  // Keep the trail mounted while the turn streams so the full multi-step flow
  // stays visible; after settle, unmount when collapsed (Codex-style compact summary).
  const shouldRenderContent = mounted || turnStreaming || typeof window === "undefined";
  const rows = shouldRenderContent ? Children.toArray(children) : [];

  return (
    <details
      className={styles.disclosure}
      data-codex-process-disclosure="true"
      data-codex-process-state={state}
      data-codex-process-expanded={expanded ? "true" : "false"}
      data-codex-process-turn-streaming={turnStreaming ? "true" : undefined}
      aria-live={running ? "polite" : undefined}
      open={mounted || turnStreaming}
    >
      <summary
        ref={summaryRef}
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
          ref={contentRef}
          id={contentId}
          className={[
            styles.contentMotion,
            expanded ? styles.contentMotionExpanded : styles.contentMotionCollapsed,
          ].join(" ")}
          aria-hidden={!expanded}
          inert={!expanded}
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
              {workSummary ? (
                <div className={styles.workBreakdown}>
                  {formatConversationTurnWorkBreakdown(workSummary, language)}
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </details>
  );
}
