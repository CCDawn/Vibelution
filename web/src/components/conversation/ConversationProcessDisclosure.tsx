import { CheckCircle2, ChevronRight, CircleAlert, CircleDot } from "lucide-react";
import React, {
  Children,
  type CSSProperties,
  type ReactNode,
  useId,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { VButton } from "../vui";
import { conversationToolPresentationLabel } from "./conversationToolPresentation";
import { activeTurnElapsedSeconds } from "./conversationActiveTurnStatusPresentation";
import {
  codexTranscriptToolDurationSeconds,
  codexTranscriptToolArguments,
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
  children: ReactNode | ((expanded: boolean) => ReactNode);
  /** Flow keeps native reasoning rows inside one work-record disclosure. */
  presentation?: "disclosure" | "flow";
  messageOrder?: ReadonlyMap<string, number>;
  onUserToggle?: ConversationProcessUserToggle;
  /** Session-owned user choice survives row identity changes and remounts. */
  expanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
  /** Work-record choice uses the same session-owned expansion store as thoughts. */
  workExpanded?: boolean;
  onWorkExpandedChange?: (expanded: boolean) => void;
  /** Stable host/turn identity for focus recovery when the live tail becomes history. */
  focusScope?: string;
  /**
   * True while the owning assistant turn is still streaming. Multi-step agents
   * often finish every current tool before the next model step; without this
   * the process rail collapses to "已处理" mid-turn and hides the trail.
   */
  turnStreaming?: boolean;
  /** Canonical turn start (message timestamp fallback); never a reasoning-segment clock. */
  turnStartedAt?: string;
  activeStage?: string;
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
  language: "zh" | "en",
  messageOrder?: ReadonlyMap<string, number>,
) {
  const failed = unrecoveredFailedCells(cells, messageOrder)[0];
  if (!failed) {
    return "";
  }
  // The expanded transcript row owns failure details. Keep the collapsed
  // summary identifiable without repeating its full error message.
  const identity = codexTranscriptToolRawName(failed) || String(failed.title || "").trim();
  return conversationToolPresentationLabel(identity, language, codexTranscriptToolArguments(failed));
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
  liveElapsedSeconds?: number | null,
  showTrailHints = true,
) {
  const state = processState(cells, messageOrder, turnStreaming);
  const labels = language === "zh"
    ? {
      completed: "已处理",
      completedWithDuration: "已工作",
      failed: "工具失败",
      running: "工作中",
      runningWithDuration: "工作中",
    }
    : {
      completed: "Processed",
      completedWithDuration: "Worked for",
      failed: "Tool failed",
      running: "Working",
      runningWithDuration: "Working for",
    };
  const duration = processDuration(cells);
  // Live work uses the turn clock; a sum of tool durations cannot describe a
  // running turn. Settled work keeps the backend summary as its first choice.
  const durationLabel = state === "running"
    ? liveElapsedSeconds == null
      ? ""
      : liveElapsedSeconds === 0
        ? (language === "zh" ? "0 秒" : "0s")
        : formatConversationTurnWorkDuration(liveElapsedSeconds * 1000, language)
    : workSummary
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
    const toolIdentity = firstFailedToolIdentity(retryFreeCells, language, messageOrder);
    if (toolIdentity) {
      parts.push(`· ${toolIdentity}`);
    } else if (showTrailHints) {
      parts.push(language === "zh" ? "· 展开查看原因" : "· expand for details");
    }
  } else if (showTrailHints && traceLength >= 3) {
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
  presentation = "disclosure",
  messageOrder,
  onUserToggle,
  expanded: controlledExpanded,
  onExpandedChange,
  workExpanded: controlledWorkExpanded,
  onWorkExpandedChange,
  focusScope,
  turnStreaming = false,
  turnStartedAt,
  activeStage,
  workSummary = null,
}: ConversationProcessDisclosureProps) {
  const state = processState(cells, messageOrder, turnStreaming);
  const running = state === "running";
  const [workChoice, setWorkChoice] = useState<boolean | undefined>();
  const workExpanded = controlledWorkExpanded ?? workChoice ?? (state !== "completed");
  const workTriggerRef = useRef<HTMLButtonElement>(null);
  const workContentRef = useRef<HTMLDivElement>(null);
  const lastRecordFocusRef = useRef<EventTarget | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!running || activeTurnElapsedSeconds(turnStartedAt, Date.now()) === null) {
      return undefined;
    }
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [running, turnStartedAt]);
  const elapsedSeconds = running ? activeTurnElapsedSeconds(turnStartedAt, nowMs) : null;
  const {
    expanded,
    handleContentTransitionEnd,
    handleSummaryClick,
    mounted,
  } = useConversationProcessDisclosureMotion(
    presentation === "flow" ? false : running,
    onUserToggle,
    controlledExpanded,
    onExpandedChange,
  );
  const contentId = useId();
  const contentRef = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    if (presentation !== "flow" || !focusScope) return;
    const record = workContentRef.current;
    return () => {
      const focused = document.activeElement;
      if (!focused || !record?.contains(focused)) return;
      // Live-tail → virtualized-history can replace the whole flow. Recover
      // only a focus lost with that removed subtree, never external focus.
      queueMicrotask(() => {
        if (focused.isConnected || document.activeElement !== document.body) return;
        const trigger = [...document.querySelectorAll<HTMLButtonElement>("button[data-codex-process-focus-scope]")]
          .find((button) => button.dataset.codexProcessFocusScope === focusScope
            && button.getAttribute("aria-expanded") === "false");
        trigger?.focus({ preventScroll: true });
      });
    };
  }, [focusScope, presentation]);
  useEffect(() => {
    // Chromium can blur a newly hidden control to body before this effect.
    // Retain the last focused record control, without stealing external focus.
    const lastFocus = lastRecordFocusRef.current;
    const focusInRecord = (target: EventTarget | null) => target instanceof Node
      && (workContentRef.current?.contains(target) || target === summaryRef.current);
    if (!workExpanded && (focusInRecord(document.activeElement)
      || (document.activeElement === document.body && focusInRecord(lastFocus)))) {
      workTriggerRef.current?.focus({ preventScroll: true });
    }
  }, [workExpanded]);
  useEffect(() => {
    if (!expanded && contentRef.current?.contains(document.activeElement)) {
      summaryRef.current?.focus({ preventScroll: true });
    }
  }, [expanded]);
  const label = processLabel(cells, language, messageOrder, turnStreaming, workSummary, elapsedSeconds, presentation !== "flow");
  const toggleLabel = language === "zh"
    ? "展开或收起处理记录"
    : "Expand or collapse process details";
  // Keep the trail mounted while the turn streams so the full multi-step flow
  // stays visible; after settle, unmount when collapsed (Codex-style compact summary).
  const shouldRenderContent = mounted || turnStreaming || typeof window === "undefined";
  const content = typeof children === "function"
    ? children(presentation === "flow" ? workExpanded : expanded)
    : children;
  const rows = shouldRenderContent ? Children.toArray(content) : [];

  if (presentation === "flow") {
    const StatusIcon = running ? CircleDot : state === "failed" ? CircleAlert : CheckCircle2;
    return (
      <div
        className={styles.flow}
        data-codex-process-disclosure="true"
        data-codex-process-presentation="flow"
        data-codex-process-state={state}
        data-codex-process-expanded={workExpanded ? "true" : "false"}
        data-codex-process-work-expanded={workExpanded ? "true" : "false"}
        data-codex-process-turn-streaming={turnStreaming ? "true" : undefined}
        data-active-turn-stage={turnStreaming ? activeStage : undefined}
        data-codex-process-elapsed-seconds={elapsedSeconds ?? undefined}
        onFocusCapture={(event) => { lastRecordFocusRef.current = event.target; }}
        onBlurCapture={(event) => {
          if (event.relatedTarget && event.relatedTarget !== document.body
            && !event.currentTarget.contains(event.relatedTarget as Node)) {
            lastRecordFocusRef.current = null;
          }
        }}
      >
        <div className={styles.flowWorkContent} ref={workContentRef} id={`${contentId}-work`} hidden={!workExpanded} inert={!workExpanded} aria-hidden={!workExpanded}>
          <div ref={contentRef} id={contentId} className={styles.flowContent}>
            {content}
          </div>
        </div>
        <div className={styles.flowStatusRow}>
          <VButton
            ref={workTriggerRef}
            type="button"
            variant="ghost"
            contentLayout="plain"
            className={styles.flowWorkToggle}
            data-codex-process-work-toggle="true"
            data-codex-process-focus-scope={focusScope}
            aria-controls={`${contentId}-work`}
            aria-expanded={workExpanded}
            aria-label={`${toggleLabel}：${label}`}
            onClick={(event) => {
              const nextExpanded = !workExpanded;
              const settle = onUserToggle?.(event.currentTarget, nextExpanded);
              setWorkChoice(nextExpanded);
              onWorkExpandedChange?.(nextExpanded);
              if (settle) window.requestAnimationFrame(settle);
            }}
          >
            <StatusIcon size={15} className={styles.flowStatusIcon} aria-hidden="true" />
            <span data-codex-process-work-status="true" role={running ? "status" : undefined}>{label}</span>
            <ChevronRight
              className={[styles.chevron, workExpanded ? styles.chevronExpanded : ""].filter(Boolean).join(" ")}
              size={12}
              aria-hidden="true"
            />
          </VButton>
        </div>
      </div>
    );
  }

  return (
    <details
      className={styles.disclosure}
      data-codex-process-disclosure="true"
      data-codex-process-state={state}
      data-codex-process-expanded={expanded ? "true" : "false"}
      data-codex-process-turn-streaming={turnStreaming ? "true" : undefined}
      data-active-turn-stage={turnStreaming ? activeStage : undefined}
      data-codex-process-elapsed-seconds={elapsedSeconds ?? undefined}
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
