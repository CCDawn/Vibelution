import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

import type { ConversationMessage } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import {
  buildConversationFindIndex,
  createConversationFindIndexCache,
  resolveConversationFindActiveIndex,
  resolveConversationFindJumpPlan,
  stepConversationFindActiveIndex,
  type ConversationFindIndexCache,
} from "./conversationFindIndex";
import {
  applyConversationFindRowMarks,
  clearConversationFindRowMarks,
  collectConversationFindMatchedMessageIds,
  CONVERSATION_FIND_HIGHLIGHT_DECAY_MS,
  flashConversationFindRow,
  queryConversationFindRowElement,
  scrollConversationFindRowIntoView,
} from "./conversationFindHighlightDom";
import type { ConversationFindBarLabels } from "./ConversationFindBar";

const CONVERSATION_FIND_DEBOUNCE_MS = 150;
const CONVERSATION_FIND_JUMP_MAX_FRAMES = 12;

export type UseConversationFindInput = {
  sessionId: string;
  t: (key: TranslationKey) => string;
  /** Settled history prefix; the in-flight live tail is never indexed. */
  historyMessages: ConversationMessage[];
  liveTailStartIndex: number;
  timelineRef: React.RefObject<HTMLDivElement | null>;
  timelineVirtualizer: Virtualizer<HTMLDivElement, Element>;
  /** Modal mirrors: while either overlay is open, Esc belongs to the overlay. */
  previewImage: ConversationImagePreviewRequest | null;
  forkDialogMessage: ConversationMessage | null;
  /** Latest-closure scroll helper (the find jump pins bottom for live-tail rows). */
  scrollTimelineToBottom: (timeline: HTMLDivElement) => void;
};

/**
 * Find-in-transcript（对话内查找）: state, index, navigation, highlight and
 * jump orchestration, extracted from ConversationView with behavior unchanged.
 * All state stays inside this hook and never crosses the route boundary.
 */
export function useConversationFind({
  sessionId,
  t,
  historyMessages,
  liveTailStartIndex,
  timelineRef,
  timelineVirtualizer,
  previewImage,
  forkDialogMessage,
  scrollTimelineToBottom,
}: UseConversationFindInput) {
  const [conversationFindOpen, setConversationFindOpen] = useState(false);
  const [conversationFindQuery, setConversationFindQuery] = useState("");
  const [conversationFindSettledQuery, setConversationFindSettledQuery] = useState("");
  const [conversationFindActiveIndex, setConversationFindActiveIndex] = useState(-1);
  const conversationFindOpenRef = useRef(false);
  conversationFindOpenRef.current = conversationFindOpen;
  const conversationFindInputRef = useRef<HTMLInputElement | null>(null);
  // 按消息 id 的索引缓存跨渲染持有：流式更新只重扫签名变化的消息。
  const conversationFindIndexCacheRef = useRef<ConversationFindIndexCache>(
    createConversationFindIndexCache(),
  );
  const conversationFindFlashCancelRef = useRef<(() => void) | null>(null);
  // 会话视图根容器：Ctrl+F / Esc 的 window 级监听用它圈定作用范围。
  const conversationSurfaceRef = useRef<HTMLDivElement | null>(null);
  // Esc 仲裁用的模态镜像：覆盖层（图片预览/分叉对话框）打开时 Esc 归覆盖层。
  const conversationFindPreviewImageRef = useRef<ConversationImagePreviewRequest | null>(null);
  conversationFindPreviewImageRef.current = previewImage;
  const conversationFindForkDialogRef = useRef<ConversationMessage | null>(null);
  conversationFindForkDialogRef.current = forkDialogMessage;
  const scrollTimelineToBottomRef = useRef(scrollTimelineToBottom);
  scrollTimelineToBottomRef.current = scrollTimelineToBottom;

  // 索引源是 historyMessages（settled 前缀；在途尾部不入索引），
  // messageOrder 即 virtualizer 行号；增量复用依赖按消息 id 的签名缓存。
  const conversationFindIndex = useMemo(
    () => buildConversationFindIndex(
      historyMessages,
      conversationFindSettledQuery,
      { cache: conversationFindIndexCacheRef.current },
    ),
    [conversationFindSettledQuery, historyMessages],
  );
  const conversationFindMatchedMessageIds = useMemo(
    () => collectConversationFindMatchedMessageIds(conversationFindIndex.matches),
    [conversationFindIndex],
  );
  const activeConversationFindMatch = conversationFindActiveIndex >= 0
    ? (conversationFindIndex.matches[conversationFindActiveIndex] ?? null)
    : null;
  // 查询串防抖（150ms）：settled 查询驱动索引；关闭时清匹配态、保留输入值。
  useEffect(() => {
    if (!conversationFindOpen) {
      setConversationFindSettledQuery("");
      return undefined;
    }
    const timer = window.setTimeout(() => {
      setConversationFindSettledQuery(conversationFindQuery);
    }, CONVERSATION_FIND_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [conversationFindOpen, conversationFindQuery]);
  // 生效命中序号：查询变化重置为首个命中；流式重建只做夹取，不打断当前位置。
  const conversationFindQueryKeyRef = useRef("");
  // 跳转去重键（查询+消息+行内序号）；closeConversationFind 归零让重开重新跳。
  const conversationFindJumpKeyRef = useRef("");
  useEffect(() => {
    const queryChanged = conversationFindQueryKeyRef.current !== conversationFindIndex.query;
    conversationFindQueryKeyRef.current = conversationFindIndex.query;
    setConversationFindActiveIndex((current) => (queryChanged
      ? resolveConversationFindActiveIndex(conversationFindIndex.matchCount, 0)
      : resolveConversationFindActiveIndex(conversationFindIndex.matchCount, current)));
  }, [conversationFindIndex]);
  const closeConversationFind = useCallback(() => {
    setConversationFindOpen(false);
    setConversationFindActiveIndex(-1);
    // 重开后再查同一词也要重新跳转（jumpKey 归零，重开不沿用上次命中）。
    conversationFindJumpKeyRef.current = "";
  }, []);
  const openConversationFind = useCallback(() => {
    setConversationFindOpen(true);
  }, []);
  // 打开时聚焦查找输入框（重开也全选，便于直接换词）。
  useEffect(() => {
    if (!conversationFindOpen) {
      return undefined;
    }
    const frame = window.requestAnimationFrame(() => {
      const input = conversationFindInputRef.current;
      if (input) {
        input.focus();
        input.select();
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [conversationFindOpen]);
  // Ctrl+F / Cmd+F 打开查找条：仅当焦点落在会话视图内或空白处（点击转录后
  // 焦点常在 body）；其他输入框（如本页之外的控件）不接管。
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.repeat || event.isComposing || event.altKey || event.shiftKey) {
        return;
      }
      if (!(event.ctrlKey || event.metaKey) || String(event.key).toLowerCase() !== "f") {
        return;
      }
      const surface = conversationSurfaceRef.current;
      const target = event.target;
      if (!surface || !(target instanceof Node)) {
        return;
      }
      if (target !== document.body && target !== document.documentElement && !surface.contains(target)) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const wasOpen = conversationFindOpenRef.current;
      openConversationFind();
      if (wasOpen) {
        // 已打开：把焦点拉回输入框（state 不变时 open 效果不会重跑）。
        window.requestAnimationFrame(() => conversationFindInputRef.current?.focus());
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [openConversationFind]);
  // Esc 关闭查找条（优先于一切停止语义）：find 输入框自带 Esc 处理并
  // preventDefault，这里兜住焦点在转录/正文时的 Esc。模态覆盖层优先。
  useEffect(() => {
    if (!conversationFindOpen) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.key !== "Escape") {
        return;
      }
      if (conversationFindPreviewImageRef.current || conversationFindForkDialogRef.current) {
        return;
      }
      const surface = conversationSurfaceRef.current;
      const target = event.target;
      if (!surface || !(target instanceof Node)) {
        return;
      }
      // 焦点常落在 body（点击转录行后不产生焦点）：与 Ctrl+F 同一判定，
      // body/根元素或会话视图内都允许关闭；其他面板的焦点不接管。
      if (
        target !== document.body
        && target !== document.documentElement
        && !surface.contains(target)
      ) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      closeConversationFind();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [conversationFindOpen, closeConversationFind]);
  const handleConversationFindPrevious = useCallback(() => {
    setConversationFindActiveIndex((current) => stepConversationFindActiveIndex(
      current,
      -1,
      conversationFindIndex.matchCount,
    ));
  }, [conversationFindIndex.matchCount]);
  const handleConversationFindNext = useCallback(() => {
    setConversationFindActiveIndex((current) => stepConversationFindActiveIndex(
      current,
      1,
      conversationFindIndex.matchCount,
    ));
  }, [conversationFindIndex.matchCount]);
  // 命中标记同步：挂载窗口内的命中行打 data 标记（CSS 出视觉）；虚拟化滚动
  // 重挂行时在 scroll 上 rAF 重放。0 命中/关闭时清除全部标记。
  useEffect(() => {
    if (!conversationFindOpen || conversationFindIndex.matchCount === 0) {
      clearConversationFindRowMarks(timelineRef.current);
      return undefined;
    }
    const timeline = timelineRef.current;
    if (!timeline) {
      return undefined;
    }
    let frame: number | null = null;
    const syncMarks = () => {
      frame = null;
      applyConversationFindRowMarks(timeline, {
        matchedMessageIds: conversationFindMatchedMessageIds,
        activeMessageId: activeConversationFindMatch?.messageId ?? null,
      });
    };
    syncMarks();
    const handleScroll = () => {
      if (frame === null) {
        frame = window.requestAnimationFrame(syncMarks);
      }
    };
    timeline.addEventListener("scroll", handleScroll, { passive: true });
    return () => {
      timeline.removeEventListener("scroll", handleScroll);
      if (frame !== null) {
        window.cancelAnimationFrame(frame);
      }
    };
  }, [
    conversationFindOpen,
    conversationFindIndex.matchCount,
    conversationFindMatchedMessageIds,
    activeConversationFindMatch,
    timelineRef,
  ]);
  // 跳转 + 3s 行高亮：目标行不在窗口先 scrollToIndex/钉底，行挂载后精对位
  // 并重放强调动画。同一命中（查询+消息+行内序号）不重复跳。
  useEffect(() => {
    if (!conversationFindOpen) {
      return undefined;
    }
    const match = activeConversationFindMatch;
    if (!match) {
      return undefined;
    }
    const jumpKey = `${conversationFindIndex.query}:${match.messageId}:${match.matchIndexInRow}`;
    if (conversationFindJumpKeyRef.current === jumpKey) {
      return undefined;
    }
    conversationFindJumpKeyRef.current = jumpKey;
    if (resolveConversationFindJumpPlan(match.messageOrder, liveTailStartIndex) === "virtual") {
      timelineVirtualizer.scrollToIndex(match.messageOrder, { align: "center" });
    } else {
      const timeline = timelineRef.current;
      if (timeline) {
        scrollTimelineToBottomRef.current(timeline);
      }
    }
    let cancelled = false;
    const frames: number[] = [];
    let attempts = 0;
    const settle = () => {
      if (cancelled) {
        return;
      }
      const row = queryConversationFindRowElement(timelineRef.current, match.messageId);
      if (!row) {
        attempts += 1;
        if (attempts <= CONVERSATION_FIND_JUMP_MAX_FRAMES) {
          frames.push(window.requestAnimationFrame(settle));
        }
        return;
      }
      scrollConversationFindRowIntoView(row);
      conversationFindFlashCancelRef.current?.();
      conversationFindFlashCancelRef.current = flashConversationFindRow(
        row,
        CONVERSATION_FIND_HIGHLIGHT_DECAY_MS,
      );
    };
    frames.push(window.requestAnimationFrame(settle));
    return () => {
      cancelled = true;
      for (const frame of frames) {
        window.cancelAnimationFrame(frame);
      }
    };
  }, [
    conversationFindOpen,
    conversationFindIndex.query,
    activeConversationFindMatch,
    liveTailStartIndex,
    timelineVirtualizer,
    timelineRef,
  ]);
  // 关闭/卸载收尾：取消挂起的 3s 衰减定时器，避免摘掉后续会话行的属性。
  useEffect(() => {
    if (conversationFindOpen) {
      return undefined;
    }
    conversationFindFlashCancelRef.current?.();
    conversationFindFlashCancelRef.current = null;
    return undefined;
  }, [conversationFindOpen]);
  useEffect(() => () => {
    conversationFindFlashCancelRef.current?.();
    conversationFindFlashCancelRef.current = null;
  }, []);
  // 会话切换不跨会话复用索引缓存。
  useEffect(() => {
    conversationFindIndexCacheRef.current.clear();
    conversationFindJumpKeyRef.current = "";
    conversationFindQueryKeyRef.current = "";
  }, [sessionId]);
  const conversationFindBarLabels: ConversationFindBarLabels = useMemo(() => ({
    title: t("findInConversationTitle"),
    placeholder: t("findInConversationPlaceholder"),
    matchCountAria: (current, total) => t("findMatchCountAria")
      .replace("{current}", String(current))
      .replace("{total}", String(total)),
    previous: t("findPreviousMatch"),
    next: t("findNextMatch"),
    close: t("findCloseBar"),
  }), [t]);

  return {
    open: conversationFindOpen,
    query: conversationFindQuery,
    setQuery: setConversationFindQuery,
    activeIndex: conversationFindActiveIndex,
    matchCount: conversationFindIndex.matchCount,
    inputRef: conversationFindInputRef,
    surfaceRef: conversationSurfaceRef,
    barLabels: conversationFindBarLabels,
    close: closeConversationFind,
    openFind: openConversationFind,
    handlePrevious: handleConversationFindPrevious,
    handleNext: handleConversationFindNext,
  };
}
