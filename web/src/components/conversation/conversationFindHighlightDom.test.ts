/** @vitest-environment happy-dom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  applyConversationFindRowMarks,
  clearConversationFindRowMarks,
  collectConversationFindMatchedMessageIds,
  CONVERSATION_FIND_ACTIVE_ATTRIBUTE,
  CONVERSATION_FIND_HIGHLIGHT_DECAY_MS,
  CONVERSATION_FIND_MATCH_ATTRIBUTE,
  flashConversationFindRow,
  queryConversationFindRowElement,
  scrollConversationFindRowIntoView,
} from "./conversationFindHighlightDom";

function row(root: HTMLElement, messageId: string): HTMLElement {
  const element = document.createElement("div");
  element.setAttribute("data-conversation-message-id", messageId);
  root.appendChild(element);
  return element;
}

describe("conversation find highlight dom", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("marks mounted matched rows and unmarks rows that left the match set", () => {
    const root = document.createElement("div");
    const keep = row(root, "keep-1");
    const drop = row(root, "drop-1");
    row(root, "plain-1");

    applyConversationFindRowMarks(root, {
      matchedMessageIds: new Set(["keep-1", "drop-1"]),
      activeMessageId: "keep-1",
    });
    expect(keep.getAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE)).toBe("true");
    expect(keep.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe("true");
    expect(drop.getAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE)).toBe("true");
    expect(drop.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBeNull();

    // 索引收缩：drop-1 不再命中 → 淡标记摘除；keep-1 保持。
    applyConversationFindRowMarks(root, {
      matchedMessageIds: new Set(["keep-1"]),
      activeMessageId: null,
    });
    expect(keep.getAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE)).toBe("true");
    expect(keep.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBeNull();
    expect(drop.hasAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE)).toBe(false);
  });

  it("returns the active row element and keeps only one active row", () => {
    const root = document.createElement("div");
    const first = row(root, "m-1");
    const second = row(root, "m-2");
    const active = applyConversationFindRowMarks(root, {
      matchedMessageIds: new Set(["m-1", "m-2"]),
      activeMessageId: "m-2",
    });
    expect(active).toBe(second);
    expect(first.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBeNull();
    expect(second.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe("true");
  });

  it("clears every match mark inside the container", () => {
    const root = document.createElement("div");
    const marked = row(root, "m-1");
    marked.setAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE, "true");
    marked.setAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE, "true");
    clearConversationFindRowMarks(root);
    expect(marked.hasAttribute(CONVERSATION_FIND_MATCH_ATTRIBUTE)).toBe(false);
    expect(marked.hasAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe(false);
    expect(clearConversationFindRowMarks(null)).toBeUndefined();
  });

  it("flash restarts the active attribute and decays after 3s via timer", () => {
    const root = document.createElement("div");
    const rowElement = row(root, "m-1");
    const cancel = flashConversationFindRow(rowElement);
    expect(rowElement.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe("true");

    vi.advanceTimersByTime(CONVERSATION_FIND_HIGHLIGHT_DECAY_MS - 1);
    expect(rowElement.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe("true");
    vi.advanceTimersByTime(1);
    expect(rowElement.hasAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe(false);

    // 取消函数阻止衰减（连续导航时旧定时器不得摘掉新命中行的属性）。
    const cancelAgain = flashConversationFindRow(rowElement);
    cancelAgain();
    vi.advanceTimersByTime(CONVERSATION_FIND_HIGHLIGHT_DECAY_MS + 10);
    expect(rowElement.getAttribute(CONVERSATION_FIND_ACTIVE_ATTRIBUTE)).toBe("true");
  });

  it("queries rows by message id through the shared row attribute", () => {
    const root = document.createElement("div");
    row(root, "m-1");
    expect(queryConversationFindRowElement(root, "m-1")).not.toBeNull();
    expect(queryConversationFindRowElement(root, "missing")).toBeNull();
    expect(queryConversationFindRowElement(null, "m-1")).toBeNull();
  });

  it("derives the matched message id set from matches", () => {
    const ids = collectConversationFindMatchedMessageIds([
      { messageId: "a" },
      { messageId: "b" },
      { messageId: "a" },
    ] as Parameters<typeof collectConversationFindMatchedMessageIds>[0]);
    expect([...ids].sort()).toEqual(["a", "b"]);
  });

  it("scrolls the row into the viewport center respecting reduced motion", () => {
    const rowElement = document.createElement("div");
    const scrollIntoView = vi.fn();
    (rowElement as unknown as { scrollIntoView: typeof scrollIntoView }).scrollIntoView = scrollIntoView;
    scrollConversationFindRowIntoView(rowElement);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "center", behavior: "smooth" });

    const matchMedia = vi.fn().mockReturnValue({ matches: true });
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = matchMedia as unknown as typeof window.matchMedia;
    try {
      scrollConversationFindRowIntoView(rowElement);
      expect(scrollIntoView).toHaveBeenLastCalledWith({ block: "center", behavior: "auto" });
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });
});
