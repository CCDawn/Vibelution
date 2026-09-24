import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useVirtualizer } from "@tanstack/react-virtual";

// Real production follow semantics, imported read-only.
import { resolveTimelineFollowState } from "../../../../src/components/conversation/conversationTimelineFollowState";

import { RowForMessage } from "../shared/MessageRow";
import type { PreviewMessage } from "../mock/syntheticConversation";

const RUNNING_TURN_DEMO_TEXT = [
  "（运行中 turn —— 不进入虚拟化窗口，独立渲染）",
  "",
  "### 增量流式渲染的双模设计",
  "",
  "流式期间只做轻量解析；未闭合围栏先补全再渲染，高亮与 mermaid 关闭。",
].join("\n");

function estimateMessageHeight(message: PreviewMessage): number {
  if (message.role === "tool") {
    return 320;
  }
  if (message.role === "user") {
    return 90;
  }
  return 170;
}

/**
 * RIGHT column of the A/B view: the proposed scheme built on
 * @tanstack/react-virtual (pattern from zai-org/ZCode ConversationTimeline,
 * Apache-2.0):
 * - the WHOLE history is virtualized (no 12/72 client window cap);
 * - dynamic measurement via measureElement + the virtualizer's internal
 *   height cache keyed by stable item keys;
 * - the running (streaming) turn renders OUTSIDE the virtualizer as a
 *   live-tail block, so tail updates never reslice the history window;
 * - stick-to-bottom via the same production follow semantics;
 * - prepend (load-earlier) keeps scroll position through the virtualizer's
 *   shouldAdjustScrollPositionOnItemSizeChange correction.
 */
export function VirtualTimeline({ messages }: { messages: PreviewMessage[] }) {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [historyMessages, setHistoryMessages] = useState<PreviewMessage[]>(messages);
  const [prepends, setPrepends] = useState(0);
  const followLatestRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const stickFrameRef = useRef<number | null>(null);

  const virtualizer = useVirtualizer({
    count: historyMessages.length,
    getScrollElement: () => viewportRef.current,
    estimateSize: (index) => estimateMessageHeight(historyMessages[index] as PreviewMessage),
    overscan: 6,
    getItemKey: (index) => (historyMessages[index] as PreviewMessage).id,
    // Prepend anchoring uses the virtualizer's built-in default: a measured
    // item ENTIRELY above the scroll offset shifts scrollTop by its delta, so
    // loading older history keeps the viewport stable without extra math.
  });

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

  // Stick to bottom while following latest: history size change OR running
  // turn growth re-pins the viewport.
  useLayoutEffect(() => {
    if (!followLatestRef.current) {
      return;
    }
    if (stickFrameRef.current !== null) {
      window.cancelAnimationFrame(stickFrameRef.current);
    }
    stickFrameRef.current = window.requestAnimationFrame(() => {
      stickFrameRef.current = null;
      scrollToBottom();
    });
  }, [virtualizer.getTotalSize(), RUNNING_TURN_DEMO_TEXT, scrollToBottom]);

  useEffect(() => {
    scrollToBottom();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadEarlier = useCallback(() => {
    setHistoryMessages((current) => {
      if (current.length >= messages.length) {
        return current;
      }
      const missing = messages.length - current.length;
      const batch = Math.min(12, missing);
      const older = messages.slice(Math.max(0, missing - batch), missing);
      setPrepends((count) => count + 1);
      return [...older, ...current];
    });
  }, [messages]);

  const handleScroll = useCallback(() => {
    const viewport = viewportRef.current;
    if (!viewport) {
      return;
    }
    const previousScrollTop = lastScrollTopRef.current;
    const next = resolveTimelineFollowState({
      scrollHeight: viewport.scrollHeight,
      clientHeight: viewport.clientHeight,
      scrollTop: viewport.scrollTop,
      previousScrollTop,
      wasFollowingLatest: followLatestRef.current,
      scrollSource: "user",
    });
    lastScrollTopRef.current = viewport.scrollTop;
    followLatestRef.current = next.shouldFollowLatest;
    setIsAtBottom(next.isAtBottom);
    if (
      viewport.scrollTop <= 56
      && viewport.scrollTop < previousScrollTop
      && historyMessages.length < messages.length
    ) {
      loadEarlier();
    }
  }, [historyMessages.length, loadEarlier, messages.length]);

  const allLoaded = historyMessages.length >= messages.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <div className="timeline-viewport" style={{ flex: "none", height: "62%" }} ref={viewportRef} onScroll={handleScroll}>
          {!allLoaded ? (
            <button className="load-earlier" onClick={loadEarlier}>
              加载更早消息（历史 {historyMessages.length}/{messages.length}）
            </button>
          ) : null}
          <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
            {virtualizer.getVirtualItems().map((item) => {
              const message = historyMessages[item.index] as PreviewMessage;
              return (
                <div
                  key={item.key}
                  data-index={item.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${item.start}px)`,
                  }}
                >
                  <RowForMessage message={message} />
                </div>
              );
            })}
          </div>
          {!isAtBottom ? (
            <button className="scroll-bottom-btn" onClick={() => {
              followLatestRef.current = true;
              scrollToBottom("smooth");
            }}>
              回到底部
            </button>
          ) : null}
        </div>
        <div className="running-turn">
          <div className="msg-meta">
            <span className="role">助手 · 运行中</span>
            <span className="state-badge on">live-tail：独立于虚拟化窗口</span>
          </div>
          <div className="md-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
              {RUNNING_TURN_DEMO_TEXT}
            </ReactMarkdown>
            <span className="streaming-caret" />
          </div>
        </div>
      </div>
      <div className="compare-stats" style={{ padding: "6px 12px", borderTop: "1px solid var(--border)" }}>
        历史 {historyMessages.length}/{messages.length}（无窗口上限）· 已挂载 {virtualizer.getVirtualItems().length} 行 · 总高 {Math.round(virtualizer.getTotalSize())}px · 前插 {prepends} 次自动锚定
      </div>
    </div>
  );
}
