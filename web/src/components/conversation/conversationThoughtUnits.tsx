import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  isThoughtScrollAtBottom,
  resolveThoughtStreamingSummary,
  type ThoughtStreamingSummary,
} from "./conversationThoughtSummary";
import styles from "./ConversationView.styles";

/**
 * Height-capped thought body; sticks to bottom while streaming until the user
 * scrolls away from the bottom, then pauses follow until they return.
 */
export function ThoughtScrollBody({
  text,
  streaming,
  className,
}: {
  text: string;
  streaming: boolean;
  className?: string;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Starts true on every (re)mount so an expand or fresh stream follows the
  // newest content; onScroll flips it off as soon as the user leaves the bottom.
  const autoFollowBottomRef = useRef(true);
  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    autoFollowBottomRef.current = isThoughtScrollAtBottom({
      clientHeight: node.clientHeight,
      scrollHeight: node.scrollHeight,
      scrollTop: node.scrollTop,
    });
  }, []);
  useLayoutEffect(() => {
    if (!streaming) {
      return;
    }
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    if (autoFollowBottomRef.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [streaming, text]);
  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      className={[styles.thoughtScrollBody, className].filter(Boolean).join(" ")}
      data-thought-scroll-body="true"
      data-thought-scroll-streaming={streaming ? "true" : undefined}
    >
      <pre className={styles.codexTranscriptReasoningText}>{text}</pre>
    </div>
  );
}

/**
 * Collapsed thought summary: the latest thought sentence in one nowrap line.
 * Overflow hides and the viewport is pushed to its end on every content or
 * width change, so the newest words stay pinned at the right edge while older
 * text rolls out to the left; a CSS mask fades both edges only once the line
 * actually overflows.
 */
export function ThoughtStreamingSummary({ text }: { text: string }) {
  const viewportRef = useRef<HTMLSpanElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  const summary: ThoughtStreamingSummary | null = resolveThoughtStreamingSummary(text);
  const summaryText = summary?.text ?? "";
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !summaryText) {
      return;
    }
    const syncSummaryViewport = () => {
      setOverflowing((current) => {
        const next = viewport.scrollWidth > viewport.clientWidth + 1;
        return current === next ? current : next;
      });
      viewport.scrollLeft = viewport.scrollWidth;
    };
    syncSummaryViewport();
    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const resizeObserver = new ResizeObserver(syncSummaryViewport);
    resizeObserver.observe(viewport);
    return () => resizeObserver.disconnect();
  }, [summaryText]);
  if (!summary) {
    return null;
  }
  return (
    <>
      <span className={styles.timelineCellSeparator} aria-hidden="true">·</span>
      <span
        ref={viewportRef}
        className={[
          styles.thoughtStreamingSummary,
          overflowing ? styles.thoughtStreamingSummaryMasked : "",
        ].filter(Boolean).join(" ")}
        data-thought-streaming-summary="true"
        data-thought-summary-mask={overflowing ? "both" : "none"}
      >
        <span className={styles.thoughtStreamingSummaryText}>{summary.text}</span>
      </span>
    </>
  );
}

/**
 * Progress narration body: clamped preview while settled, full scrollable text
 * while live or expanded. No box chrome so it reads lighter than the thinking lane.
 */
export function ProgressScrollBody({
  text,
  streaming,
  clamped,
}: {
  text: string;
  streaming: boolean;
  clamped: boolean;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    if (!streaming || clamped) {
      return;
    }
    const node = scrollRef.current;
    if (!node) {
      return;
    }
    node.scrollTop = node.scrollHeight;
  }, [clamped, streaming, text]);
  if (clamped) {
    return (
      <div className={styles.codexTranscriptProgressClamped} data-codex-progress-clamped="true">
        {text}
      </div>
    );
  }
  return (
    <div
      ref={scrollRef}
      className={styles.codexTranscriptProgressBody}
      data-codex-progress-body="true"
      data-codex-progress-streaming={streaming ? "true" : undefined}
    >
      <pre className={styles.codexTranscriptProgressText}>{text}</pre>
    </div>
  );
}

const PROGRESS_CLAMP_LINES = 3;
const PROGRESS_CLAMP_CHARACTERS_PER_LINE = 72;

/**
 * Codex parity: only offer an expand toggle when expanding would reveal
 * something the 3-line clamp hides; a short update stays static text.
 */
export function progressTextExceedsClamp(text: string) {
  const segments = String(text ?? "").split("\n");
  let lines = 0;
  for (const segment of segments) {
    lines += Math.max(1, Math.ceil(segment.length / PROGRESS_CLAMP_CHARACTERS_PER_LINE));
  }
  return lines > PROGRESS_CLAMP_LINES;
}

export function replaceDividerPlaceholder(template: string, token: string, value: string) {
  return template.split(`{${token}}`).join(value);
}

const THOUGHT_DURATION_TICK_MS = 1000;

/**
 * ZCode thought-duration semantics, client clock only: the timer starts at the
 * unit's first live render, ticks every second while (and only while) the unit
 * is expanded and live, and freezes when the unit settles. Units that arrive
 * already settled (history loads) have no client-clock reading — they show a
 * duration only when the server carried canonical reasoning stamps
 * (`settledDurationSeconds`, see conversationThoughtDuration.ts); otherwise
 * they render nothing rather than fabricate one.
 */
export const ThoughtDurationLabel = React.memo(function ThoughtDurationLabel({
  live,
  expanded,
  settledDurationSeconds,
  settledSecondsTemplate,
  settledMomentsLabel,
}: {
  live: boolean;
  expanded: boolean;
  /** Server-derived total for units that arrived settled; undefined when the stamps are absent. */
  settledDurationSeconds?: number;
  settledSecondsTemplate: string;
  settledMomentsLabel: string;
}) {
  const startedAtRef = useRef<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState<number | null>(null);

  // First live render opens the client-side measurement window.
  useEffect(() => {
    if (live && startedAtRef.current === null) {
      startedAtRef.current = Date.now();
    }
  }, [live]);

  // Per-second cadence is tied to visibility: only an expanded live unit ticks.
  // A self-rescheduling timeout (not an interval) keeps the ticking scoped to
  // this label and clears with the effect on expand/settle changes.
  useEffect(() => {
    if (!live || !expanded || startedAtRef.current === null) {
      return undefined;
    }
    let timer: number | null = null;
    const syncElapsed = () => {
      setElapsedSeconds(
        Math.max(0, Math.round((Date.now() - (startedAtRef.current ?? Date.now())) / THOUGHT_DURATION_TICK_MS)),
      );
      timer = window.setTimeout(syncElapsed, THOUGHT_DURATION_TICK_MS);
    };
    syncElapsed();
    return () => {
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [live, expanded]);

  // Freeze once: settle closes the window with the last honest reading.
  useEffect(() => {
    if (!live && startedAtRef.current !== null) {
      setElapsedSeconds(
        Math.max(0, Math.round((Date.now() - startedAtRef.current) / THOUGHT_DURATION_TICK_MS)),
      );
    }
  }, [live]);

  if (live) {
    // Nothing ticked yet (collapsed live unit): no duration label.
    if (elapsedSeconds === null) {
      return null;
    }
    return (
      <span
        className={styles.thoughtDuration}
        data-thought-duration="live"
      >
        <span className={styles.timelineCellSeparator} aria-hidden="true">·</span>
        {`${elapsedSeconds}s`}
      </span>
    );
  }
  // Settled: server-derived canonical stamps win (they bracket the true
  // measurement window; the client window only opens at first render), then
  // the client-clock frozen reading. Units with neither show nothing.
  const frozenSeconds = settledDurationSeconds
    ?? (startedAtRef.current !== null && elapsedSeconds !== null ? elapsedSeconds : null);
  if (frozenSeconds === null) {
    return null;
  }
  const frozenLabel = frozenSeconds < 1
    ? settledMomentsLabel
    : replaceDividerPlaceholder(settledSecondsTemplate, "seconds", String(frozenSeconds));
  return (
    <span
      className={styles.thoughtDuration}
      data-thought-duration="settled"
    >
      <span className={styles.timelineCellSeparator} aria-hidden="true">·</span>
      {frozenLabel}
    </span>
  );
});
