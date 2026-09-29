/**
 * 对话内查找的行级高亮与滚动定位 —— DOM 侧辅助（纯 DOM 属性 + CSS）。
 *
 * 转录行由 react-virtual 虚拟化，只渲染可见窗口；本模块不操纵 React 管理的
 * DOM 内容，只读写行元素上的 data 属性（data-conversation-find-match /
 * data-conversation-find-active），视觉表现全部由 conversationFindHighlight.css
 * 承担：当前命中行带 3s 衰减动画，普通命中行保持淡标记。
 *
 * 跳转流程（调用方编排，见 ConversationView 集成）：
 * 1. 目标行不在窗口 → 先 virtualizer.scrollToIndex / 钉底，等行挂载；
 * 2. 行挂载后 applyConversationFindRowMarks 打命中标记 + flashConversationFindRow
 *    重放 3s 强调动画（setTimeout 到期移除属性，避免残留）；
 * 3. 用户滚动导致行重挂 → 调用方在 scroll 上重放 applyConversationFindRowMarks。
 */
import type { ConversationFindMatch } from "./conversationFindIndex";
import "./conversationFindHighlight.css";

/** 转录行身份属性（ConversationView 渲染行时已写入）。 */
export const CONVERSATION_FIND_ROW_ATTRIBUTE = "data-conversation-message-id";

/** 命中行淡标记属性（值恒为 "true"）。 */
export const CONVERSATION_FIND_MATCH_ATTRIBUTE = "data-conversation-find-match";

/** 当前命中行强调属性（值恒为 "true"）。 */
export const CONVERSATION_FIND_ACTIVE_ATTRIBUTE = "data-conversation-find-active";

/** 当前命中行强调高亮的衰减时长（毫秒）。 */
export const CONVERSATION_FIND_HIGHLIGHT_DECAY_MS = 3000;

export function queryConversationFindRowElement(
  root: HTMLElement | null | undefined,
  messageId: string,
): HTMLElement | null {
  if (!root || !messageId) {
    return null;
  }
  return root.querySelector<HTMLElement>(`[${CONVERSATION_FIND_ROW_ATTRIBUTE}="${CSS.escape(messageId)}"]`);
}

function setRowMark(row: HTMLElement, attribute: string, marked: boolean) {
  if (marked) {
    if (row.getAttribute(attribute) !== "true") {
      row.setAttribute(attribute, "true");
    }
    return;
  }
  if (row.hasAttribute(attribute)) {
    row.removeAttribute(attribute);
  }
}

/**
 * 同步挂载窗口内所有命中标记：
 * - matchedMessageIds 中的行打 CONVERSATION_FIND_MATCH_ATTRIBUTE；
 * - 已不在命中集合中的行摘除标记（索引收缩后不留残影）；
 * - activeMessageId 的行额外打 CONVERSATION_FIND_ACTIVE_ATTRIBUTE。
 * 返回当前命中行元素（未挂载/无当前命中 → null）。
 */
export function applyConversationFindRowMarks(
  root: HTMLElement,
  options: {
    matchedMessageIds: ReadonlySet<string>;
    activeMessageId: string | null;
  },
): HTMLElement | null {
  const rows = root.querySelectorAll<HTMLElement>(`[${CONVERSATION_FIND_ROW_ATTRIBUTE}]`);
  let activeRow: HTMLElement | null = null;
  for (const row of Array.from(rows)) {
    const messageId = row.getAttribute(CONVERSATION_FIND_ROW_ATTRIBUTE) ?? "";
    const matched = messageId !== "" && options.matchedMessageIds.has(messageId);
    setRowMark(row, CONVERSATION_FIND_MATCH_ATTRIBUTE, matched);
    const isActive = matched && messageId === options.activeMessageId;
    setRowMark(row, CONVERSATION_FIND_ACTIVE_ATTRIBUTE, isActive);
    if (isActive) {
      activeRow = row;
    }
  }
  return activeRow;
}

/** 清除容器内全部命中标记（find 条关闭/卸载时调用）。 */
export function clearConversationFindRowMarks(root: HTMLElement | null | undefined) {
  if (!root) {
    return;
  }
  for (const attribute of [CONVERSATION_FIND_MATCH_ATTRIBUTE, CONVERSATION_FIND_ACTIVE_ATTRIBUTE]) {
    for (const row of Array.from(
      root.querySelectorAll<HTMLElement>(`[${attribute}]`),
    )) {
      row.removeAttribute(attribute);
    }
  }
}

/**
 * 重放当前命中行的 3s 强调动画：摘属性 → 强制 reflow → 重打属性，让 CSS
 * 动画从头播放；DECAY_MS 后移除 active 属性（淡标记由 match 属性承担）。
 * 返回取消函数（再次跳转前调用，避免旧定时器摘掉新行的属性）。
 */
export function flashConversationFindRow(
  row: HTMLElement,
  decayMs: number = CONVERSATION_FIND_HIGHLIGHT_DECAY_MS,
): () => void {
  row.removeAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE);
  // 强制同步布局，让同帧内重打的属性重新触发 CSS 动画（行内连续导航必需）。
  void row.offsetWidth;
  row.setAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE, "true");
  if (typeof window === "undefined" || decayMs <= 0) {
    return () => undefined;
  }
  const timer = window.setTimeout(() => {
    row.removeAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE);
  }, decayMs);
  return () => {
    window.clearTimeout(timer);
  };
}

/** 命中行滚入视口中央（虚拟化 scrollToIndex 之后的精对位；respect reduced motion）。 */
export function scrollConversationFindRowIntoView(
  row: HTMLElement,
  behavior: ScrollBehavior = "smooth",
) {
  const reducedMotion =
    typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  row.scrollIntoView({ block: "center", behavior: reducedMotion ? "auto" : behavior });
}

/** 命中集合 → 消息 id 集合（marks 同步与索引重建解耦）。 */
export function collectConversationFindMatchedMessageIds(
  matches: readonly ConversationFindMatch[],
): Set<string> {
  const ids = new Set<string>();
  for (const match of matches) {
    ids.add(match.messageId);
  }
  return ids;
}
