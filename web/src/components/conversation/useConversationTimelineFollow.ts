import { useCallback, useEffect, useLayoutEffect, type Dispatch, type MutableRefObject, type RefObject, type SetStateAction } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

import {
  captureConversationProcessScrollAnchor,
  restoreConversationProcessScrollAnchor,
} from "./conversationProcessScrollAnchor";
import {
  shouldLoadEarlierConversationMessages,
  shouldPreferServerEarlierLoad,
  TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
} from "./conversationHistoryWindow";
import {
  captureTimelineRowKeyAnchor,
  restoreTimelineRowKeyAnchor,
  type TimelineScrollRowKeyAnchor,
} from "./timelineScrollAnchor";
import {
  peekSessionTimelineScroll,
  rememberSessionTimelineScroll,
  restoreSessionTimelineScroll,
} from "./conversationSessionScrollMemory";
import {
  freshTimelineUserScrollIntent,
  isTimelineNearBottom,
  reconcileFollowingBeforeContentStick,
  resolveTimelineFollowState,
  shouldKeepFollowingLatestOnProcessToggle,
  shouldStickTimelineToBottomOnContentResize,
  TIMELINE_CONTENT_WIDTH_RESIZE_SETTLE_MS,
  timelineKeyboardScrollIntent,
  timelineTouchScrollIntent,
  timelineWheelScrollIntent,
  type TimelineScrollSource,
  type TimelineUserScrollIntent,
} from "./conversationTimelineFollowState";
import type { ConversationTurnNavEntry } from "./conversationTurnNavigation";

// Prepend anchor correction: bounded frames for measurements to land before
// the viewport position is declared final (2px tolerance = subpixel jitter).
const TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES = 30;
const TIMELINE_ANCHOR_CORRECTION_TOLERANCE_PX = 2;

export type TimelineHistoryAnchorCorrection = {
  anchor: TimelineScrollRowKeyAnchor;
  /** Message count at capture; correction starts once the prepend commits. */
  startLength: number;
  attempts: number;
  fallbackDone: boolean;
  /** A viewport rhythm change needs correction even without a prepend. */
  geometryReflow?: boolean;
};

type TimelineFollowApi = {
  scrollTimelineToBottom: (
    timeline: HTMLDivElement,
    options?: { followLatest?: boolean; behavior?: ScrollBehavior },
  ) => void;
};

export type UseConversationTimelineFollowInput = {
  /** Assigned during render so callers above this hook keep a stable delegate. */
  timelineFollowApiRef: MutableRefObject<TimelineFollowApi | null>;
  sessionId: string;
  timelineRef: RefObject<HTMLDivElement | null>;
  timelineContentRef: RefObject<HTMLDivElement | null>;
  readingViewportAnchorRef: MutableRefObject<TimelineScrollRowKeyAnchor | null>;
  historyScrollAnchorRef: MutableRefObject<TimelineScrollRowKeyAnchor | null>;
  historyAnchorCorrectingRef: MutableRefObject<TimelineHistoryAnchorCorrection | null>;
  followLatestRef: MutableRefObject<boolean>;
  atBottomRef: MutableRefObject<boolean>;
  userScrollIntentRef: MutableRefObject<TimelineUserScrollIntent>;
  userScrollIntentAtRef: MutableRefObject<number>;
  ignoreNextProgrammaticFollowRef: MutableRefObject<boolean>;
  lastTimelineScrollTopRef: MutableRefObject<number>;
  lastTimelineContentWidthRef: MutableRefObject<number>;
  contentWidthChangingUntilRef: MutableRefObject<number>;
  streamingScrollFrameRef: MutableRefObject<number | null>;
  autoScrollToLatestRef: MutableRefObject<boolean>;
  initializedSessionRef: MutableRefObject<string>;
  pinnedLatestUserMessageIdRef: MutableRefObject<string>;
  setIsAtBottom: Dispatch<SetStateAction<boolean>>;
  autoScrollToLatest: boolean;
  latestUserMessageId: string;
  timelineScrollSignal: string;
  streamingTimelineScrollSignal: string;
  narrowTimelineViewport: boolean;
  activeTimelineMessages: readonly unknown[];
  displayMessages: readonly unknown[];
  earlierMessagesLoading: boolean;
  hasEarlierMessages: boolean;
  hiddenHistorySignalCount: number;
  onLoadEarlierMessages?: () => void;
  visibleMessageCount: number;
  timelineLiveTailStartIndex: number;
  timelineVirtualizer: Virtualizer<HTMLDivElement, Element>;
  preserveCurrentExpansionDefaults: () => void;
};

/**
 * Stick-to-bottom, prepend-anchor correction, and earlier-history load for the
 * transcript viewport. Extracted from ConversationView; effect order inside
 * this hook matches the previous shell order.
 */
export function useConversationTimelineFollow({
  timelineFollowApiRef,
  sessionId,
  timelineRef,
  timelineContentRef,
  readingViewportAnchorRef,
  historyScrollAnchorRef,
  historyAnchorCorrectingRef,
  followLatestRef,
  atBottomRef,
  userScrollIntentRef,
  userScrollIntentAtRef,
  ignoreNextProgrammaticFollowRef,
  lastTimelineScrollTopRef,
  lastTimelineContentWidthRef,
  contentWidthChangingUntilRef,
  streamingScrollFrameRef,
  autoScrollToLatestRef,
  initializedSessionRef,
  pinnedLatestUserMessageIdRef,
  setIsAtBottom,
  autoScrollToLatest,
  latestUserMessageId,
  timelineScrollSignal,
  streamingTimelineScrollSignal,
  narrowTimelineViewport,
  activeTimelineMessages,
  displayMessages,
  earlierMessagesLoading,
  hasEarlierMessages,
  hiddenHistorySignalCount,
  onLoadEarlierMessages,
  visibleMessageCount,
  timelineLiveTailStartIndex,
  timelineVirtualizer,
  preserveCurrentExpansionDefaults,
}: UseConversationTimelineFollowInput) {
  function rememberUserScrollIntent(intent: TimelineUserScrollIntent) {
    if (intent === "none") {
      return;
    }
    if (historyAnchorCorrectingRef.current?.geometryReflow) {
      historyAnchorCorrectingRef.current = null;
      historyScrollAnchorRef.current = null;
      readingViewportAnchorRef.current = null;
    }
    userScrollIntentRef.current = intent;
    userScrollIntentAtRef.current = performance.now();
  }

  function currentUserScrollIntent() {
    return freshTimelineUserScrollIntent(
      userScrollIntentRef.current,
      userScrollIntentAtRef.current,
      performance.now(),
    );
  }

  function contentWidthIsChanging() {
    return performance.now() < contentWidthChangingUntilRef.current;
  }

  function noteTimelineContentWidth(width: number) {
    if (!Number.isFinite(width) || width <= 0) {
      return;
    }
    const previous = lastTimelineContentWidthRef.current;
    if (previous > 0 && width !== previous) {
      contentWidthChangingUntilRef.current = performance.now() + TIMELINE_CONTENT_WIDTH_RESIZE_SETTLE_MS;
    }
    lastTimelineContentWidthRef.current = width;
  }

  function reconcileFollowBeforeStick(timeline: HTMLDivElement) {
    const next = reconcileFollowingBeforeContentStick({
      following: followLatestRef.current,
      isAtBottom: isTimelineNearBottom({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
      }),
      userScrollIntent: currentUserScrollIntent(),
      scrollTop: timeline.scrollTop,
      lastObservedScrollTop: lastTimelineScrollTopRef.current,
    });
    followLatestRef.current = next;
    return next;
  }

  function scrollTimelineToBottom(
    timeline: HTMLDivElement,
    options: { followLatest?: boolean; behavior?: ScrollBehavior } = {},
  ) {
    if (options.followLatest) {
      readingViewportAnchorRef.current = null;
      rememberUserScrollIntent("towardBottom");
    }
    const wasAtBottom = atBottomRef.current;
    ignoreNextProgrammaticFollowRef.current = true;
    if (options.behavior) {
      timeline.scrollTo({ top: timeline.scrollHeight, behavior: options.behavior });
    } else {
      timeline.scrollTop = timeline.scrollHeight;
    }
    atBottomRef.current = true;
    if (options.followLatest) {
      followLatestRef.current = true;
    }
    lastTimelineScrollTopRef.current = timeline.scrollTop;
    if (!wasAtBottom) {
      setIsAtBottom(true);
    }
  }

  function scheduleTimelineScrollToBottom() {
    const timeline = timelineRef.current;
    if (contentWidthIsChanging()) {
      return;
    }
    if (timeline && !reconcileFollowBeforeStick(timeline)) {
      return;
    }
    if (streamingScrollFrameRef.current !== null) {
      return;
    }
    streamingScrollFrameRef.current = window.requestAnimationFrame(() => {
      streamingScrollFrameRef.current = null;
      const timeline = timelineRef.current;
      if (!timeline || !followLatestRef.current) {
        return;
      }
      scrollTimelineToBottom(timeline);
    });
  }

  timelineFollowApiRef.current = { scrollTimelineToBottom };

  const handleProcessDisclosureUserToggle = useCallback((summary: HTMLElement, _nextExpanded: boolean) => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return undefined;
    }
    const keepFollowing = shouldKeepFollowingLatestOnProcessToggle({
      autoScrollToLatest: autoScrollToLatestRef.current,
      followingLatest: followLatestRef.current,
      scrollHeight: timeline.scrollHeight,
      clientHeight: timeline.clientHeight,
      scrollTop: timeline.scrollTop,
    });
    if (keepFollowing) {
      // Expanding near the tail: stay stuck to bottom so growth follows downward.
      followLatestRef.current = true;
      atBottomRef.current = true;
      setIsAtBottom(true);
      return () => {
        if (followLatestRef.current) {
          scrollTimelineToBottom(timeline);
        }
        lastTimelineScrollTopRef.current = timeline.scrollTop;
      };
    }
    // Reading history: pin the summary so expand/collapse does not yank the viewport.
    const anchor = captureConversationProcessScrollAnchor(summary);
    atBottomRef.current = false;
    followLatestRef.current = false;
    lastTimelineScrollTopRef.current = timeline.scrollTop;
    setIsAtBottom(false);

    return () => {
      restoreConversationProcessScrollAnchor(timeline, summary, anchor);
      lastTimelineScrollTopRef.current = timeline.scrollTop;
    };
  }, []);

  // Stick-to-bottom: re-pin when timeline viewport or content height changes while following.
  // Observe the inner content host — the scroll container's border box often stays fixed while
  // scrollHeight grows, so observing only `timeline` misses streaming / expand growth.
  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver(() => {
      noteTimelineContentWidth(timeline.clientWidth);
      if (shouldStickTimelineToBottomOnContentResize({
        autoScrollToLatest: autoScrollToLatestRef.current,
        followingLatest: followLatestRef.current,
        contentWidthChanging: contentWidthIsChanging(),
      })) {
        scheduleTimelineScrollToBottom();
      }
    });
    observer.observe(timeline);
    const content = timelineContentRef.current;
    if (content) {
      observer.observe(content);
    }
    return () => observer.disconnect();
  }, [sessionId, activeTimelineMessages.length > 0]);

  useLayoutEffect(() => {
    const pending = historyAnchorCorrectingRef.current;
    if (!pending || !pending.anchor) {
      return;
    }
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (!pending.geometryReflow && activeTimelineMessages.length === pending.startLength) {
      // Capture done, prepend not committed yet: keep the anchor pending.
      return;
    }
    if (!pending.fallbackDone) {
      // First pass after the prepend: exact row-key restore when the anchor
      // row is mounted, scrollHeight-delta fallback otherwise (the fallback
      // drifts by the estimate error of all prepended rows; the correction
      // frames below eliminate that residual).
      pending.fallbackDone = true;
      if (restoreTimelineRowKeyAnchor(timeline, pending.anchor)) {
        atBottomRef.current = false;
        followLatestRef.current = false;
        lastTimelineScrollTopRef.current = timeline.scrollTop;
        setIsAtBottom(false);
      }
      return;
    }
    // Correction frames: re-run until the anchor row is mounted at its captured
    // viewport offset. Measurements streaming in after the prepend keep
    // re-rendering this effect, so the residual estimate error converges to
    // zero within a couple of frames instead of shipping a visible jump.
    const rootTop = timeline.getBoundingClientRect().top;
    let anchorRow: Element | null = null;
    for (const row of timeline.querySelectorAll("[data-conversation-row-key]")) {
      if (row.getAttribute("data-conversation-row-key") === pending.anchor.rowKey) {
        anchorRow = row;
        break;
      }
    }
    if (!anchorRow) {
      pending.attempts += 1;
      if (pending.attempts > TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES) {
        historyAnchorCorrectingRef.current = null;
        historyScrollAnchorRef.current = null;
      }
      return;
    }
    const drift = anchorRow.getBoundingClientRect().top - rootTop - pending.anchor.offsetTop;
    if (Math.abs(drift) <= TIMELINE_ANCHOR_CORRECTION_TOLERANCE_PX) {
      historyAnchorCorrectingRef.current = null;
      historyScrollAnchorRef.current = null;
      return;
    }
    timeline.scrollTop += drift;
    lastTimelineScrollTopRef.current = timeline.scrollTop;
  });

  useLayoutEffect(() => {
    // Breakpoint changes alter virtual row offsets as well as text wrapping.
    // Keep a following reader at the tail after react-virtual's next measure.
    const timeline = timelineRef.current;
    if (!timeline) return undefined;
    const anchor = historyAnchorCorrectingRef.current?.geometryReflow
      ? historyAnchorCorrectingRef.current.anchor : readingViewportAnchorRef.current;
    // CSS can temporarily clamp scrollTop to the bottom before the media
    // callback runs. A remembered reading anchor takes precedence over that.
    const following = !anchor && followLatestRef.current;
    if (anchor) followLatestRef.current = false;
    if (!following && !anchor) return undefined;
    const intentAtStart = userScrollIntentAtRef.current;
    let frame = 0;
    let remainingFrames = TIMELINE_ANCHOR_CORRECTION_MAX_FRAMES;
    const restoreViewport = () => {
      const current = timelineRef.current;
      if (!current || userScrollIntentAtRef.current > intentAtStart) return;
      if (following && followLatestRef.current) {
        scrollTimelineToBottom(current);
      } else if (anchor) {
        // Browser/virtualizer clamps may briefly report "at bottom" while
        // remeasuring. Preserve the pre-resize reading intent through them.
        followLatestRef.current = false;
        atBottomRef.current = false;
        setIsAtBottom(false);
        restoreTimelineRowKeyAnchor(current, anchor);
        lastTimelineScrollTopRef.current = current.scrollTop;
      }
      // react-virtual measures rows in rAF; retain the target through those
      // measurements rather than clearing it after the first matching paint.
      if (remainingFrames-- > 0) frame = window.requestAnimationFrame(restoreViewport);
      else if (!followLatestRef.current) readingViewportAnchorRef.current = captureTimelineRowKeyAnchor(current);
    };
    restoreViewport();
    return () => window.cancelAnimationFrame(frame);
  }, [narrowTimelineViewport, sessionId]);

  useLayoutEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    if (initializedSessionRef.current !== sessionId) {
      initializedSessionRef.current = sessionId;
      pinnedLatestUserMessageIdRef.current = latestUserMessageId;
      // Codex resume: restore mid-history viewport when revisiting a thread.
      const saved = peekSessionTimelineScroll(sessionId);
      const restored = restoreSessionTimelineScroll(timeline, saved);
      if (restored.restored) {
        followLatestRef.current = false;
        atBottomRef.current = false;
        setIsAtBottom(false);
        lastTimelineScrollTopRef.current = restored.scrollTop;
        // Sticky→full hydrate and virtual row measure can grow height after first paint.
        window.requestAnimationFrame(() => {
          const nextTimeline = timelineRef.current;
          if (!nextTimeline || followLatestRef.current) {
            return;
          }
          const again = restoreSessionTimelineScroll(nextTimeline, saved);
          lastTimelineScrollTopRef.current = again.scrollTop;
        });
        return;
      }
      scrollTimelineToBottom(timeline, { followLatest: true });
      return;
    }
    // New outbound user turn (send / edit-resubmit that keeps identity still updates
    // content via timelineScrollSignal; a brand-new latest user id always rejoins the tail).
    const latestUserChanged = Boolean(latestUserMessageId)
      && latestUserMessageId !== pinnedLatestUserMessageIdRef.current;
    if (latestUserChanged) {
      pinnedLatestUserMessageIdRef.current = latestUserMessageId;
      if (autoScrollToLatest) {
        scrollTimelineToBottom(timeline, { followLatest: true });
        return;
      }
    }
    if (!autoScrollToLatest) {
      return;
    }
    const userScrollIntent = currentUserScrollIntent();
    if (userScrollIntent === "awayFromBottom") {
      followLatestRef.current = false;
    } else if (
      !followLatestRef.current
      && isTimelineNearBottom({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
      })
    ) {
      // Content growth while still near the bottom re-enables follow even if a prior
      // expand briefly suspended it. An upward wheel recorded before this commit wins.
      followLatestRef.current = true;
      atBottomRef.current = true;
      setIsAtBottom(true);
    }
    if (followLatestRef.current) {
      scheduleTimelineScrollToBottom();
    }
  }, [autoScrollToLatest, latestUserMessageId, sessionId, timelineScrollSignal]);

  useEffect(() => {
    if (!streamingTimelineScrollSignal || !autoScrollToLatest || !followLatestRef.current) {
      return undefined;
    }
    scheduleTimelineScrollToBottom();
    return undefined;
  }, [autoScrollToLatest, sessionId, streamingTimelineScrollSignal]);

  useEffect(() => () => {
    if (streamingScrollFrameRef.current !== null) {
      window.cancelAnimationFrame(streamingScrollFrameRef.current);
      streamingScrollFrameRef.current = null;
    }
    // Capture leave-viewport scroll even when scroll listener already detached.
    rememberSessionTimelineScroll(sessionId, {
      scrollTop: lastTimelineScrollTopRef.current,
      followingLatest: followLatestRef.current,
    });
  }, [sessionId]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return undefined;
    }
    const wheelTargetConsumesScroll = (target: EventTarget | null, deltaY: number) => {
      if (!(target instanceof HTMLElement) || target === timeline) {
        return false;
      }
      let node: HTMLElement | null = target;
      while (node && node !== timeline) {
        if (
          node instanceof HTMLInputElement
          || node instanceof HTMLTextAreaElement
          || node.isContentEditable
        ) {
          return true;
        }
        const overflowY = window.getComputedStyle(node).overflowY;
        if (
          (overflowY === "auto" || overflowY === "scroll")
          && node.scrollHeight > node.clientHeight + 1
        ) {
          if (deltaY < 0 && node.scrollTop > 0) {
            return true;
          }
          if (deltaY > 0 && node.scrollTop + node.clientHeight < node.scrollHeight - 1) {
            return true;
          }
        }
        node = node.parentElement;
      }
      return false;
    };
    const onWheel = (event: WheelEvent) => {
      if (wheelTargetConsumesScroll(event.target, event.deltaY)) {
        return;
      }
      rememberUserScrollIntent(timelineWheelScrollIntent(event.deltaY));
    };
    let lastTouchY = 0;
    const onTouchStart = (event: TouchEvent) => {
      lastTouchY = event.touches[0]?.clientY ?? lastTouchY;
    };
    const onTouchMove = (event: TouchEvent) => {
      const nextY = event.touches[0]?.clientY ?? lastTouchY;
      rememberUserScrollIntent(timelineTouchScrollIntent(lastTouchY, nextY));
      lastTouchY = nextY;
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      const editableTarget = target instanceof HTMLElement && (
        target.isContentEditable
        || target.tagName === "INPUT"
        || target.tagName === "TEXTAREA"
      );
      rememberUserScrollIntent(timelineKeyboardScrollIntent({
        key: event.key,
        shiftKey: event.shiftKey,
        editableTarget,
      }));
    };
    timeline.addEventListener("wheel", onWheel, { passive: true });
    timeline.addEventListener("touchstart", onTouchStart, { passive: true });
    timeline.addEventListener("touchmove", onTouchMove, { passive: true });
    window.addEventListener("keydown", onKeyDown);
    return () => {
      timeline.removeEventListener("wheel", onWheel);
      timeline.removeEventListener("touchstart", onTouchStart);
      timeline.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [sessionId]);

  useEffect(() => {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    const handleScroll = (consumeProgrammatic = true) => {
      const previousScrollTop = lastTimelineScrollTopRef.current;
      if (shouldLoadEarlierConversationMessages({
        clientHeight: timeline.clientHeight,
        hiddenMessageCount: hiddenHistorySignalCount,
        previousScrollTop,
        scrollHeight: timeline.scrollHeight,
        scrollTop: timeline.scrollTop,
        thresholdPx: TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
      })) {
        revealEarlierTimelineMessages();
      }
      const programmaticFollow = consumeProgrammatic && ignoreNextProgrammaticFollowRef.current;
      if (consumeProgrammatic) {
        ignoreNextProgrammaticFollowRef.current = false;
      }
      const scrollSource: TimelineScrollSource = programmaticFollow ? "programmatic" : "user";
      const nextState = resolveTimelineFollowState({
        scrollHeight: timeline.scrollHeight,
        clientHeight: timeline.clientHeight,
        scrollTop: timeline.scrollTop,
        previousScrollTop,
        wasFollowingLatest: followLatestRef.current,
        scrollSource,
        userScrollIntent: currentUserScrollIntent(),
      });
      lastTimelineScrollTopRef.current = timeline.scrollTop;
      atBottomRef.current = nextState.isAtBottom;
      followLatestRef.current = nextState.shouldFollowLatest;
      setIsAtBottom(nextState.isAtBottom);
      if (!nextState.shouldFollowLatest && !historyAnchorCorrectingRef.current?.geometryReflow) {
        readingViewportAnchorRef.current = captureTimelineRowKeyAnchor(timeline);
      } else if (nextState.shouldFollowLatest && currentUserScrollIntent() === "towardBottom") {
        readingViewportAnchorRef.current = null;
      }
      rememberSessionTimelineScroll(sessionId, {
        scrollTop: timeline.scrollTop,
        followingLatest: nextState.shouldFollowLatest,
      });
    };
    const onTimelineScroll = () => handleScroll(true);
    handleScroll(false);
    timeline.addEventListener("scroll", onTimelineScroll);
    return () => {
      timeline.removeEventListener("scroll", onTimelineScroll);
      rememberSessionTimelineScroll(sessionId, {
        scrollTop: lastTimelineScrollTopRef.current,
        followingLatest: followLatestRef.current,
      });
    };
  }, [
    displayMessages.length,
    earlierMessagesLoading,
    hasEarlierMessages,
    hiddenHistorySignalCount,
    onLoadEarlierMessages,
    sessionId,
    visibleMessageCount,
  ]);

  function scrollToBottom() {
    const timeline = timelineRef.current;
    if (!timeline) {
      return;
    }
    scrollTimelineToBottom(timeline, { followLatest: true, behavior: "smooth" });
  }

  /**
   * Minimap jump: virtualized history rows go through the virtualizer's
   * scrollToIndex; the live tail (last entry) just pins to the bottom.
   * Reduced motion falls back to instant jumps.
   */
  function handleTurnNavigate(entry: ConversationTurnNavEntry) {
    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const behavior: ScrollBehavior = reducedMotion ? "auto" : "smooth";
    if (entry.anchorRowIndex < timelineLiveTailStartIndex) {
      timelineVirtualizer.scrollToIndex(entry.anchorRowIndex, { behavior, align: "start" });
      return;
    }
    const timeline = timelineRef.current;
    if (timeline) {
      scrollTimelineToBottom(timeline, { followLatest: false, behavior });
    }
  }

  function revealEarlierTimelineMessages() {
    const preferServerEarlier = shouldPreferServerEarlierLoad({
      visibleMessageCount,
      displayMessageCount: displayMessages.length,
      hasEarlierMessages: Boolean(hasEarlierMessages),
      earlierMessagesLoading: Boolean(earlierMessagesLoading),
    });
    if (!preferServerEarlier || !onLoadEarlierMessages) {
      // U5 with full-history virtualization: every local message is already
      // rendered (visibleMessageCount === displayMessages.length), so there is
      // no client window left to expand — earlier history is server pages only.
      return;
    }
    preserveCurrentExpansionDefaults();
    historyScrollAnchorRef.current = captureTimelineRowKeyAnchor(timelineRef.current);
    historyAnchorCorrectingRef.current = historyScrollAnchorRef.current
      ? {
        anchor: historyScrollAnchorRef.current,
        startLength: activeTimelineMessages.length,
        attempts: 0,
        fallbackDone: false,
      }
      : null;
    atBottomRef.current = false;
    followLatestRef.current = false;
    setIsAtBottom(false);
    onLoadEarlierMessages();
  }

  return {
    handleProcessDisclosureUserToggle,
    scrollToBottom,
    handleTurnNavigate,
  };
}
