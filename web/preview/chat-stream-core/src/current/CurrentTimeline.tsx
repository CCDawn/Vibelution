import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

// Real production logic modules, imported read-only (zero modification).
import {
  INITIAL_VISIBLE_MESSAGE_COUNT,
  shouldLoadEarlierConversationMessages,
  nextVisibleMessageLimit,
  resolveVisibleMessageCount,
  TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
} from "../../../../src/components/conversation/conversationHistoryWindow";
import {
  CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX,
  recordConversationRowHeight,
  resolveConversationVirtualRange,
  resolveTimelineFollowState,
  type TimelineUserScrollIntent,
} from "../../../../src/components/conversation/conversationTimelineFollowState";
import {
  captureTimelineRowKeyAnchor,
  restoreTimelineRowKeyAnchor,
} from "../../../../src/components/conversation/timelineScrollAnchor";

import { RowForMessage } from "../shared/MessageRow";
import type { PreviewMessage } from "../mock/syntheticConversation";

/**
 * LEFT column of the A/B view: a faithful replica of the current production
 * transcript strategy (as diagnosed in ConversationView.tsx):
 * - client message window: 12 initial, +12 per upward gesture, soft cap 72;
 * - spacer virtualization via the real resolveConversationVirtualRange with a
 *   rowKey->height cache fed by ResizeObserver + recordConversationRowHeight;
 * - follow-latest semantics from the real resolveTimelineFollowState;
 * - prepend anchoring via the real capture/restoreTimelineRowKeyAnchor.
 */
export function CurrentTimeline({ messages }: { messages: PreviewMessage[] }) {
  const [visibleLimit, setVisibleLimit] = useState(INITIAL_VISIBLE_MESSAGE_COUNT);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(600);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [heightVersion, setHeightVersion] = useState(0);
  const [renderedRowCount, setRenderedRowCount] = useState(0);

  const viewportRef = useRef<HTMLDivElement | null>(null);
  const rowHeightCacheRef = useRef(new Map<string, number>());
  const rowNodesRef = useRef(new Map<string, HTMLElement>());
  const rowObserversRef = useRef(new Map<string, ResizeObserver>());
  const followLatestRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const scrollIntentUntilRef = useRef(0);
  const pendingAnchorRef = useRef<ReturnType<typeof captureTimelineRowKeyAnchor>>(null);

  const displayCount = resolveVisibleMessageCount({
    displayMessageCount: messages.length,
    visibleLimit,
  });
  // Current window shows the LAST N messages of the session.
  const windowStart = messages.length - displayCount;
  const windowedMessages = useMemo(
    () => messages.slice(windowStart),
    [messages, windowStart],
  );

  const measuredHeights = useMemo(
    () => windowedMessages.map((message) => rowHeightCacheRef.current.get(message.id) ?? 0),
    // heightVersion re-projects the cache into the range resolver.
    [windowedMessages, heightVersion],
  );

  const range = useMemo(
    () => resolveConversationVirtualRange({
      itemCount: windowedMessages.length,
      scrollTop,
      viewportHeight,
      followingLatest: followLatestRef.current,
      heights: measuredHeights,
    }),
    [windowedMessages.length, scrollTop, viewportHeight, measuredHeights],
  );

  const visibleRows = useMemo(
    () => windowedMessages.slice(range.start, range.end),
    [windowedMessages, range.start, range.end],
  );

  useEffect(() => {
    setRenderedRowCount(visibleRows.length);
  }, [visibleRows.length]);

  const bindRow = useCallback((rowKey: string, node: HTMLElement | null) => {
    if (!node) {
      rowNodesRef.current.delete(rowKey);
      rowObserversRef.current.get(rowKey)?.disconnect();
      rowObserversRef.current.delete(rowKey);
      return;
    }
    if (rowNodesRef.current.get(rowKey) === node && rowObserversRef.current.has(rowKey)) {
      return;
    }
    rowObserversRef.current.get(rowKey)?.disconnect();
    rowObserversRef.current.delete(rowKey);
    const publish = (height: number) => {
      const minDeltaPx = followLatestRef.current ? 8 : 2;
      if (recordConversationRowHeight(rowHeightCacheRef.current, rowKey, height, { minDeltaPx })) {
        setHeightVersion((version) => version + 1);
      }
    };
    publish(node.getBoundingClientRect().height);
    if (typeof ResizeObserver === "undefined") {
      rowNodesRef.current.set(rowKey, node);
      return;
    }
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      const height = entry?.borderBoxSize?.[0]?.blockSize
        ?? entry?.contentRect?.height
        ?? node.getBoundingClientRect().height;
      publish(height);
    });
    observer.observe(node);
    rowObserversRef.current.set(rowKey, observer);
    rowNodesRef.current.set(rowKey, node);
  }, []);

  const rowRef = useCallback((rowKey: string) => (node: HTMLDivElement | null) => {
    bindRow(rowKey, node);
  }, [bindRow]);

  // Restore the row-key anchor after a prepend (load-earlier).
  useLayoutEffect(() => {
    const anchor = pendingAnchorRef.current;
    if (!anchor) {
      return;
    }
    pendingAnchorRef.current = null;
    if (restoreTimelineRowKeyAnchor(viewportRef.current, anchor)) {
      followLatestRef.current = false;
      setIsAtBottom(false);
    }
  }, [displayCount]);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    if (behavior === "smooth") {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior });
    } else {
      viewport.scrollTop = viewport.scrollHeight;
    }
  }, []);

  // Stick to bottom while following latest and content grows (measure-in).
  useLayoutEffect(() => {
    if (followLatestRef.current) {
      scrollToBottom();
    }
  }, [range.totalHeightPx, scrollToBottom]);

  useEffect(() => {
    scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadEarlier = useCallback(() => {
    if (displayCount >= messages.length) {
      return;
    }
    pendingAnchorRef.current = captureTimelineRowKeyAnchor(viewportRef.current);
    setVisibleLimit((limit) => nextVisibleMessageLimit({
      currentLimit: limit,
      displayMessageCount: messages.length,
    }));
  }, [displayCount, messages.length]);

  const handleScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const intent: TimelineUserScrollIntent =
      viewport.scrollTop < lastScrollTopRef.current
        ? (Date.now() < scrollIntentUntilRef.current ? "awayFromBottom" : "none")
        : "none";
    const next = resolveTimelineFollowState({
      scrollHeight: viewport.scrollHeight,
      clientHeight: viewport.clientHeight,
      scrollTop: viewport.scrollTop,
      previousScrollTop: lastScrollTopRef.current,
      wasFollowingLatest: followLatestRef.current,
      scrollSource: "user",
      userScrollIntent: intent,
    });
    lastScrollTopRef.current = viewport.scrollTop;
    followLatestRef.current = next.shouldFollowLatest;
    setIsAtBottom(next.isAtBottom);
    setScrollTop(viewport.scrollTop);
    setViewportHeight(viewport.clientHeight);
    if (
      shouldLoadEarlierConversationMessages({
        clientHeight: viewport.clientHeight,
        hiddenMessageCount: windowStart,
        previousScrollTop: lastScrollTopRef.current,
        scrollHeight: viewport.scrollHeight,
        scrollTop: viewport.scrollTop,
        thresholdPx: TIMELINE_HISTORY_LOAD_THRESHOLD_PX,
      })
    ) {
      loadEarlier();
    }
  }, [loadEarlier, windowStart]);

  const hiddenCount = windowStart;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <div className="timeline-viewport" ref={viewportRef} onScroll={handleScroll}>
        {hiddenCount > 0 ? (
          <button className="load-earlier" onClick={loadEarlier}>
            加载更早消息（窗口 {displayCount}/{messages.length}）
          </button>
        ) : null}
        {range.topSpacerPx > 0 ? <div style={{ height: range.topSpacerPx }} aria-hidden /> : null}
        {visibleRows.map((message) => (
          <div key={message.id} ref={rowRef(message.id)}>
            <RowForMessage message={message} />
          </div>
        ))}
        {range.bottomSpacerPx > 0 ? <div style={{ height: range.bottomSpacerPx }} aria-hidden /> : null}
        {!isAtBottom ? (
          <button className="scroll-bottom-btn" onClick={() => {
            followLatestRef.current = true;
            scrollToBottom("smooth");
          }}>
            回到底部
          </button>
        ) : null}
      </div>
      <div className="compare-stats" style={{ padding: "6px 12px", borderTop: "1px solid var(--border)" }}>
        窗口 {displayCount}/{messages.length} · 本帧渲染 {renderedRowCount} 行 · 估算 {CONVERSATION_VIRTUAL_ROW_ESTIMATE_PX}px · 缓存高度 {rowHeightCacheRef.current.size}
      </div>
    </div>
  );
}
