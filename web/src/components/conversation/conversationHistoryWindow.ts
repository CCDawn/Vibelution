export type ConversationHistoryLoadInput = {
  clientHeight: number;
  hiddenMessageCount: number;
  previousScrollTop: number;
  scrollHeight: number;
  scrollTop: number;
  thresholdPx: number;
};

/** First-paint DOM window for the transcript timeline (U5). */
export const INITIAL_VISIBLE_MESSAGE_COUNT = 12;

/** How many additional messages to reveal per upward history gesture. */
export const TIMELINE_HISTORY_LOAD_BATCH_COUNT = 12;

/** Pixel threshold near the top edge that counts as “load earlier”. */
export const TIMELINE_HISTORY_LOAD_THRESHOLD_PX = 56;

/**
 * Soft guidance ceiling for client-rendered rows (U5).
 * Used to prefer server earlier-load when the local window is already large;
 * local history can still expand past this so users are never trapped.
 */
export const MAX_CLIENT_VISIBLE_MESSAGE_COUNT = 72;

export function shouldLoadEarlierConversationMessages({
  clientHeight,
  hiddenMessageCount,
  previousScrollTop,
  scrollHeight,
  scrollTop,
  thresholdPx,
}: ConversationHistoryLoadInput) {
  if (hiddenMessageCount <= 0) {
    return false;
  }
  if (scrollHeight <= clientHeight) {
    return true;
  }
  if (scrollTop <= 0) {
    return true;
  }
  return scrollTop <= thresholdPx && scrollTop < previousScrollTop;
}

/**
 * Next client-side visible limit after an upward history gesture.
 * Always bounded by displayMessageCount; never traps local history.
 */
export function nextVisibleMessageLimit(input: {
  currentLimit: number;
  displayMessageCount: number;
  batchSize?: number;
}): number {
  const batchSize = input.batchSize ?? TIMELINE_HISTORY_LOAD_BATCH_COUNT;
  return Math.min(input.displayMessageCount, input.currentLimit + batchSize);
}

/** Effective render count for the current window (last N of display list). */
export function resolveVisibleMessageCount(input: {
  displayMessageCount: number;
  visibleLimit: number;
}): number {
  return Math.min(input.displayMessageCount, Math.max(0, input.visibleLimit));
}

/**
 * Prefer fetching older pages from the server once the local window is large,
 * instead of only expanding an already-heavy DOM (U5).
 */
export function shouldPreferServerEarlierLoad(input: {
  visibleMessageCount: number;
  displayMessageCount: number;
  hasEarlierMessages: boolean;
  earlierMessagesLoading: boolean;
  softMaxRendered?: number;
}): boolean {
  if (!input.hasEarlierMessages || input.earlierMessagesLoading) {
    return false;
  }
  if (input.visibleMessageCount >= input.displayMessageCount) {
    return true;
  }
  const softMax = input.softMaxRendered ?? MAX_CLIENT_VISIBLE_MESSAGE_COUNT;
  return input.visibleMessageCount >= softMax;
}
