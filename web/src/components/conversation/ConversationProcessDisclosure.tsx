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
  /**
   * True while the owning assistant turn is still streaming. Multi-step agents
   * often finish every current tool before the next model step; without this
   * the process rail collapses to "已处理" mid-turn and hides the trail.
   */
  turnStreaming?: boolean;
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

function retryAttemptLabel(cell: CodexTranscriptCell, language: "zh" | "en") {
  const content = [cell.summary, cell.text, cell.title]
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .join(" ");
  const match = content.match(/(?:第\s*)?(\d+)\s*(?:\/|of)\s*(\d+)\s*(?:次|attempts?)?/i);
  if (!match) {
    return "";
  }
  return language === "zh" ? `（${match[1]}/${match[2]}）` : ` (${match[1]}/${match[2]})`;
}

export function processLabel(
  cells: readonly CodexTranscriptCell[],
  language: "zh" | "en",
  messageOrder?: ReadonlyMap<string, number>,
  turnStreaming = false,
) {
  const state = processState(cells, messageOrder, turnStreaming);
  const labels = language === "zh"
    ? { completed: "已处理", failed: "工具失败", running: "处理中" }
    : { completed: "Processed", failed: "Tool failed", running: "Processing" };
  const duration = processDuration(cells);
  const retry = [...cells].reverse().find(isRetryCell);
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
  } else if (cells.length >= 3) {
    // Hint that the disclosure holds a multi-step tool trail (including mid-turn).
    parts.push(language === "zh" ? `· ${cells.length} 步` : `· ${cells.length} steps`);
  }
  if (retry) {
    const attempt = retryAttemptLabel(retry, language);
    if (state === "running" && retry.status !== "completed") {
      parts.push(language === "zh" ? `· 模型重试中${attempt}` : `· Retrying model${attempt}`);
    } else {
      parts.push(language === "zh" ? "· 含模型重试" : "· Included model retry");
    }
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
  const label = processLabel(cells, language, messageOrder, turnStreaming);
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
