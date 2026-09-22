const TIMELINE_BOTTOM_THRESHOLD_PX = 32;
const TIMELINE_UPWARD_SCROLL_THRESHOLD_PX = 2;

/** Wheel/touch intent stays valid until the matching scroll event can land. */
export const TIMELINE_USER_SCROLL_INTENT_TTL_MS = 1200;
/** Ignore follow changes for the scroll event caused by our own scrollTop write. */
export const TIMELINE_LAYOUT_SCROLL_GUARD_MS = 250;
/** Width resize remeasures many rows across frames; do not chase scrollTop per row. */
export const TIMELINE_CONTENT_WIDTH_RESIZE_SETTLE_MS = 120;

export type TimelineScrollSource = "user" | "programmatic" | "layout";

/** Direction captured before the scroll event, which arrives one frame later. */
export type TimelineUserScrollIntent = "none" | "awayFromBottom" | "towardBottom" | "unknown";

export type TimelineFollowStateInput = {
  scrollHeight: number;
  clientHeight: number;
  scrollTop: number;
  previousScrollTop: number;
  wasFollowingLatest: boolean;
  /** Defaults to user so a scrollbar drag still releases follow. */
  scrollSource?: TimelineScrollSource;
  /** Fresh wheel/touch/keyboard direction. Away-from-bottom wins over geometry. */
  userScrollIntent?: TimelineUserScrollIntent;
};

export type TimelineFollowState = {
  isAtBottom: boolean;
  shouldFollowLatest: boolean;
};

export function isTimelineNearBottom(
  { scrollHeight, clientHeight, scrollTop }: Pick<TimelineFollowStateInput, "scrollHeight" | "clientHeight" | "scrollTop">,
  thresholdPx = TIMELINE_BOTTOM_THRESHOLD_PX,
) {
  return scrollHeight - scrollTop - clientHeight <= thresholdPx;
}

export function timelineWheelScrollIntent(deltaY: number): TimelineUserScrollIntent {
  if (!Number.isFinite(deltaY) || deltaY === 0) {
    return "none";
  }
  return deltaY < 0 ? "awayFromBottom" : "towardBottom";
}

/** Finger moving down reads earlier content, so the viewport should move up. */
export function timelineTouchScrollIntent(
  previousClientY: number,
  nextClientY: number,
): TimelineUserScrollIntent {
  if (!Number.isFinite(previousClientY) || !Number.isFinite(nextClientY) || previousClientY === nextClientY) {
    return "none";
  }
  return nextClientY > previousClientY ? "awayFromBottom" : "towardBottom";
}

export function timelineKeyboardScrollIntent(input: {
  key: string;
  shiftKey: boolean;
  editableTarget: boolean;
}): TimelineUserScrollIntent {
  if (input.editableTarget) {
    return "none";
  }
  if (input.key === "ArrowUp" || input.key === "PageUp" || input.key === "Home") {
    return "awayFromBottom";
  }
  if (input.key === "ArrowDown" || input.key === "PageDown" || input.key === "End") {
    return "towardBottom";
  }
  if (input.key === " ") {
    return input.shiftKey ? "awayFromBottom" : "towardBottom";
  }
  return "none";
}

export function freshTimelineUserScrollIntent(
  intent: TimelineUserScrollIntent,
  notedAtMs: number,
  nowMs: number,
): TimelineUserScrollIntent {
  if (intent === "none" || !Number.isFinite(notedAtMs) || !Number.isFinite(nowMs)) {
    return "none";
  }
  if (nowMs - notedAtMs > TIMELINE_USER_SCROLL_INTENT_TTL_MS) {
    return "none";
  }
  return intent;
}

/**
 * Content commits can stick to the bottom before the scroll event arrives.
 * An upward wheel in that gap must win; layout scrollTop jitter must not.
 */
export function reconcileFollowingBeforeContentStick(input: {
  following: boolean;
  isAtBottom: boolean;
  userScrollIntent?: TimelineUserScrollIntent;
  scrollTop: number;
  lastObservedScrollTop: number;
  scrollEpsilonPx?: number;
}): boolean {
  const intent = input.userScrollIntent ?? "unknown";
  if (intent === "awayFromBottom") {
    return false;
  }
  if (intent === "none") {
    return input.following;
  }
  if (input.isAtBottom) {
    return true;
  }
  const epsilon = input.scrollEpsilonPx ?? TIMELINE_UPWARD_SCROLL_THRESHOLD_PX;
  if (input.scrollTop < input.lastObservedScrollTop - epsilon) {
    return false;
  }
  return input.following;
}

export function resolveTimelineFollowState({
  scrollHeight,
  clientHeight,
  scrollTop,
  previousScrollTop,
  wasFollowingLatest,
  scrollSource = "user",
  userScrollIntent = "none",
}: TimelineFollowStateInput): TimelineFollowState {
  const isAtBottom = isTimelineNearBottom({ scrollHeight, clientHeight, scrollTop });
  if (userScrollIntent === "awayFromBottom") {
    return { isAtBottom, shouldFollowLatest: false };
  }
  if (scrollSource !== "user") {
    return { isAtBottom, shouldFollowLatest: wasFollowingLatest };
  }
  if (isAtBottom) {
    return { isAtBottom: true, shouldFollowLatest: true };
  }
  const userScrolledUp = scrollTop < previousScrollTop - TIMELINE_UPWARD_SCROLL_THRESHOLD_PX;
  return {
    isAtBottom: false,
    shouldFollowLatest: userScrolledUp ? false : wasFollowingLatest,
  };
}

/**
 * Stick-to-bottom: while following latest, content growth (streaming / reflow) should
 * re-pin the viewport even when a ResizeObserver reports size change without a user scroll.
 */
export function shouldStickTimelineToBottomOnContentResize(input: {
  autoScrollToLatest: boolean;
  followingLatest: boolean;
  /** Width resize remeasures rows across frames; chasing scrollTop jitters the list. */
  contentWidthChanging?: boolean;
}): boolean {
  if (input.contentWidthChanging) {
    return false;
  }
  return Boolean(input.autoScrollToLatest && input.followingLatest);
}

/**
 * Explicit process expand/collapse:
 * - near bottom / already following → keep stick-to-bottom so growth follows the tail
 * - reading history → suspend follow and pin the summary instead
 */
export function shouldKeepFollowingLatestOnProcessToggle(input: {
  autoScrollToLatest: boolean;
  followingLatest: boolean;
  scrollHeight: number;
  clientHeight: number;
  scrollTop: number;
}): boolean {
  if (!input.autoScrollToLatest) {
    return false;
  }
  if (input.followingLatest) {
    return true;
  }
  return isTimelineNearBottom({
    scrollHeight: input.scrollHeight,
    clientHeight: input.clientHeight,
    scrollTop: input.scrollTop,
  });
}

/** Fallback row height when a turn has not been measured yet (px). */
export const CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX = 120;

export type ConversationVirtualRange = {
  start: number;
  end: number;
  topSpacerPx: number;
  bottomSpacerPx: number;
  totalHeightPx: number;
};

/** Build prefix offsets: offsets[i] = sum(heights[0..i-1]). Length = heights.length + 1. */
export function buildConversationHeightOffsets(heights: readonly number[]): number[] {
  const offsets = new Array<number>(heights.length + 1);
  offsets[0] = 0;
  for (let i = 0; i < heights.length; i += 1) {
    const size = Number.isFinite(heights[i]) && heights[i] > 0
      ? heights[i]
      : CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX;
    offsets[i + 1] = offsets[i] + size;
  }
  return offsets;
}

/** Binary search: largest index with offsets[index] <= scrollTop. */
export function findConversationIndexAtOffset(
  offsets: readonly number[],
  scrollTop: number,
): number {
  if (offsets.length <= 1) {
    return 0;
  }
  let low = 0;
  let high = offsets.length - 2;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (offsets[mid] <= scrollTop) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return Math.max(0, high);
}

/**
 * Windowed virtual range using measured (or estimated) row heights.
 * Spacers use prefix sums so stick-bottom / scroll restoration stay stable as rows measure in.
 */
export function resolveConversationVirtualRange(input: {
  itemCount: number;
  scrollTop: number;
  viewportHeight: number;
  followingLatest: boolean;
  /** Per-index heights; missing/invalid entries fall back to estimate. */
  heights?: readonly number[];
  estimatePx?: number;
  overscan?: number;
}): ConversationVirtualRange {
  const count = Math.max(0, input.itemCount);
  if (count === 0) {
    return { start: 0, end: 0, topSpacerPx: 0, bottomSpacerPx: 0, totalHeightPx: 0 };
  }
  const estimate = input.estimatePx ?? CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX;
  const overscan = input.overscan ?? 4;
  const heights = new Array<number>(count);
  for (let i = 0; i < count; i += 1) {
    const measured = input.heights?.[i];
    heights[i] = Number.isFinite(measured) && (measured as number) > 0
      ? (measured as number)
      : estimate;
  }
  const offsets = buildConversationHeightOffsets(heights);
  const totalHeightPx = offsets[count];

  // Small lists: render fully.
  if (count <= 24) {
    return {
      start: 0,
      end: count,
      topSpacerPx: 0,
      bottomSpacerPx: 0,
      totalHeightPx,
    };
  }

  let start: number;
  let end: number;
  if (input.followingLatest) {
    end = count;
    // Walk backward until we cover a viewport (+ overscan rows).
    let covered = 0;
    start = count;
    while (start > 0 && covered < input.viewportHeight) {
      start -= 1;
      covered += heights[start];
    }
    start = Math.max(0, start - overscan);
    // Stabilize stick-bottom: always keep a min tail row count so estimate→measure
    // transitions do not shrink the mounted window and jolt the tail.
    const minTailRows = Math.ceil(input.viewportHeight / estimate) + overscan * 2;
    const minRowsStart = Math.max(0, count - minTailRows);
    start = Math.min(start, minRowsStart);
  } else {
    start = findConversationIndexAtOffset(offsets, Math.max(0, input.scrollTop));
    start = Math.max(0, start - overscan);
    const viewEnd = input.scrollTop + Math.max(input.viewportHeight, 1);
    end = findConversationIndexAtOffset(offsets, viewEnd) + 1;
    end = Math.min(count, end + overscan);
  }
  if (end < start) {
    end = start;
  }
  return {
    start,
    end,
    topSpacerPx: offsets[start],
    bottomSpacerPx: Math.max(0, totalHeightPx - offsets[end]),
    totalHeightPx,
  };
}

/** Merge a measured row height into a cache, ignoring no-op / invalid sizes. */
export function recordConversationRowHeight(
  cache: Map<string, number>,
  rowKey: string,
  heightPx: number,
  options?: { minDeltaPx?: number },
): boolean {
  const key = String(rowKey || "").trim();
  if (!key) {
    return false;
  }
  const next = Math.round(heightPx);
  if (!Number.isFinite(next) || next <= 0) {
    return false;
  }
  const previous = cache.get(key);
  const minDelta = options?.minDeltaPx ?? 2;
  if (previous !== undefined && Math.abs(previous - next) < minDelta) {
    return false;
  }
  if (previous === next) {
    return false;
  }
  cache.set(key, next);
  return true;
}
