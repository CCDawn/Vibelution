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
