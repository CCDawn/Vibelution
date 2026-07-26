const TIMELINE_BOTTOM_THRESHOLD_PX = 32;
const TIMELINE_UPWARD_SCROLL_THRESHOLD_PX = 2;

export type TimelineFollowStateInput = {
  scrollHeight: number;
  clientHeight: number;
  scrollTop: number;
  previousScrollTop: number;
  wasFollowingLatest: boolean;
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

export function resolveTimelineFollowState({
  scrollHeight,
  clientHeight,
  scrollTop,
  previousScrollTop,
  wasFollowingLatest,
}: TimelineFollowStateInput): TimelineFollowState {
  const isAtBottom = isTimelineNearBottom({ scrollHeight, clientHeight, scrollTop });
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
}): boolean {
  return Boolean(input.autoScrollToLatest && input.followingLatest);
}

/** Estimated row height for virtual spacer math (px). Tuned for dense chat turns. */
export const CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX = 120;

/**
 * Windowed virtual range over an already client-windowed timeline.
 * Keeps head/tail anchors; only overscans around the scroll focus.
 * When following latest, focus the tail so stick-bottom stays stable.
 */
export function resolveConversationVirtualRange(input: {
  itemCount: number;
  scrollTop: number;
  viewportHeight: number;
  followingLatest: boolean;
  estimatePx?: number;
  overscan?: number;
}): { start: number; end: number; topSpacerPx: number; bottomSpacerPx: number } {
  const count = Math.max(0, input.itemCount);
  if (count === 0) {
    return { start: 0, end: 0, topSpacerPx: 0, bottomSpacerPx: 0 };
  }
  const estimate = input.estimatePx ?? CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX;
  const overscan = input.overscan ?? 4;
  // Small lists: render fully (virtualization overhead not worth it).
  if (count <= 24) {
    return { start: 0, end: count, topSpacerPx: 0, bottomSpacerPx: 0 };
  }
  let start: number;
  let end: number;
  if (input.followingLatest) {
    end = count;
    start = Math.max(0, count - Math.ceil(input.viewportHeight / estimate) - overscan);
  } else {
    start = Math.max(0, Math.floor(input.scrollTop / estimate) - overscan);
    end = Math.min(count, Math.ceil((input.scrollTop + input.viewportHeight) / estimate) + overscan);
  }
  if (end < start) {
    end = start;
  }
  return {
    start,
    end,
    topSpacerPx: start * estimate,
    bottomSpacerPx: Math.max(0, (count - end) * estimate),
  };
}
