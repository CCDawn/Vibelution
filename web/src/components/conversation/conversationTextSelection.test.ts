// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";

import {
  buildQuotedDraftText,
  CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE,
  extractConversationSelectionSnapshot,
  findConversationSelectionMessageId,
  resolveSelectionQuoteMenuPosition,
  SELECTION_QUOTE_MENU_GAP_PX,
  SELECTION_QUOTE_MENU_HEIGHT_PX,
  type ConversationSelectionLike,
  type ConversationSelectionRangeLike,
  type ConversationSelectionRect,
} from "./conversationTextSelection";

function stubRect(partial: Partial<ConversationSelectionRect>): ConversationSelectionRect {
  return {
    top: 0,
    left: 0,
    width: 0,
    height: 0,
    bottom: 0,
    right: 0,
    ...partial,
  };
}

function stubRange(
  startContainer: Node,
  endContainer: Node,
  rect: ConversationSelectionRect,
): ConversationSelectionRangeLike {
  return {
    startContainer,
    endContainer,
    getBoundingClientRect: () => rect,
  };
}

function stubSelection(
  ranges: ConversationSelectionRangeLike[],
  text: string,
  isCollapsed = false,
): ConversationSelectionLike {
  return {
    rangeCount: ranges.length,
    isCollapsed,
    toString: () => text,
    getRangeAt: (index: number) => ranges[index]!,
  };
};

describe("conversationTextSelection", () => {
  it("returns null for empty, collapsed, or container-less selections", () => {
    const container = document.createElement("div");
    const node = document.createTextNode("内容");
    container.appendChild(node);

    expect(extractConversationSelectionSnapshot(null, container)).toBeNull();
    expect(extractConversationSelectionSnapshot(stubSelection([], "", true), container)).toBeNull();
    expect(
      extractConversationSelectionSnapshot(stubSelection([stubRange(node, node, stubRect({}))], "内容"), container),
    ).toBeNull();
    expect(
      extractConversationSelectionSnapshot(stubSelection([stubRange(node, node, stubRect({}))], "   "), container),
    ).toBeNull();
    expect(
      extractConversationSelectionSnapshot(
        stubSelection([stubRange(node, node, stubRect({}))], "内容"),
        null,
      ),
    ).toBeNull();
  });

  it("rejects selections that are not fully inside the timeline container", () => {
    const container = document.createElement("div");
    const inside = document.createTextNode("时间线内");
    const outside = document.createTextNode("时间线外");
    const outsideHost = document.createElement("div");
    outsideHost.appendChild(outside);

    const crossing = stubSelection(
      [stubRange(inside, outside, stubRect({ top: 10, left: 0, width: 40, height: 10, bottom: 20, right: 40 }))],
      "时间线内 时间线外",
    );
    expect(extractConversationSelectionSnapshot(crossing, container)).toBeNull();
  });

  it("unions multi-range rects and keeps the normalized plain text", () => {
    const container = document.createElement("div");
    const first = document.createTextNode("第一段");
    const second = document.createTextNode("第二段");
    container.appendChild(first);
    container.appendChild(second);

    const selection = stubSelection(
      [
        stubRange(first, first, stubRect({ top: 10, left: 8, width: 40, height: 12, bottom: 22, right: 48 })),
        stubRange(second, second, stubRect({ top: 40, left: 2, width: 60, height: 12, bottom: 52, right: 62 })),
      ],
      "第一段\r\n第二段",
    );
    const snapshot = extractConversationSelectionSnapshot(selection, container);
    expect(snapshot?.text).toBe("第一段\n第二段");
    expect(snapshot?.rect).toEqual(stubRect({ top: 10, left: 2, width: 60, height: 42, bottom: 52, right: 62 }));
    // No message row in this fixture, so the structured reference stays empty.
    expect(snapshot?.sourceMessageId).toBe("");
  });

  it("resolves the selection's owning message id from the anchor row wrapper", () => {
    const container = document.createElement("div");
    const row = document.createElement("div");
    row.setAttribute(CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE, "message-anchor-1");
    const nested = document.createElement("div");
    const text = document.createTextNode("被划选的原文");
    nested.appendChild(text);
    row.appendChild(nested);
    container.appendChild(row);

    expect(findConversationSelectionMessageId(text, container)).toBe("message-anchor-1");
    expect(findConversationSelectionMessageId(nested, container)).toBe("message-anchor-1");

    // A second row wins when the anchor lives inside it.
    const otherRow = document.createElement("div");
    otherRow.setAttribute(CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE, "message-anchor-2");
    const otherText = document.createTextNode("另一行");
    otherRow.appendChild(otherText);
    container.appendChild(otherRow);
    expect(findConversationSelectionMessageId(otherText, container)).toBe("message-anchor-2");

    // Anchors outside any message row resolve to "".
    const bare = document.createTextNode("没有行容器");
    container.appendChild(bare);
    expect(findConversationSelectionMessageId(bare, container)).toBe("");
    expect(findConversationSelectionMessageId(text, null)).toBe("");
  });

  it("carries the anchor's message id on the selection snapshot", () => {
    const container = document.createElement("div");
    const row = document.createElement("div");
    row.setAttribute(CONVERSATION_SELECTION_MESSAGE_ATTRIBUTE, "message-anchor-1");
    const text = document.createTextNode("被划选的原文");
    row.appendChild(text);
    container.appendChild(row);

    const snapshot = extractConversationSelectionSnapshot(
      stubSelection([stubRange(text, text, stubRect({ top: 10, left: 0, width: 40, height: 10, bottom: 20, right: 40 }))], "被划选的原文"),
      container,
    );
    expect(snapshot?.sourceMessageId).toBe("message-anchor-1");
  });

  it("centers the menu on the selection instead of the pane's left edge", () => {
    const position = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 160, left: 300, width: 50, height: 20, bottom: 180, right: 350 }),
      { width: 1200, height: 800 },
      { width: 208, height: 40 },
    );
    expect(position.above).toBe(true);
    expect(position.left).toBe(325 - 104);
    expect(position.top).toBe(160 - SELECTION_QUOTE_MENU_GAP_PX);

    const wideSelection = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 200, left: 80, width: 1040, height: 48, bottom: 248, right: 1120 }),
      { width: 1200, height: 800 },
      { width: 208, height: 40 },
    );
    expect(wideSelection.left).toBe(600 - 104);
  });

  it("keeps the menu inside the viewport and flips below when the top is tight", () => {
    const clamped = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 160, left: 1100, width: 80, height: 20, bottom: 180, right: 1180 }),
      { width: 1200, height: 800 },
      { width: 208, height: 40 },
    );
    expect(clamped.left).toBe(1200 - 208 - 12);

    const flipped = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 20, left: 40, width: 50, height: 20, bottom: 40, right: 90 }),
      { width: 1200, height: 800 },
      { width: 208, height: 40 },
    );
    expect(flipped.above).toBe(false);
    expect(flipped.top).toBe(40 + SELECTION_QUOTE_MENU_GAP_PX);
    expect(SELECTION_QUOTE_MENU_HEIGHT_PX).toBeGreaterThan(0);
  });

  it("reads range geometry from prototype getters", () => {
    const container = document.createElement("div");
    const text = document.createTextNode("被划选的原文");
    container.appendChild(text);
    const rect = Object.create(null, {
      top: { get: () => 160, enumerable: false },
      left: { get: () => 300, enumerable: false },
      width: { get: () => 50, enumerable: false },
      height: { get: () => 20, enumerable: false },
      bottom: { get: () => 180, enumerable: false },
      right: { get: () => 350, enumerable: false },
    }) as ConversationSelectionRect;

    const snapshot = extractConversationSelectionSnapshot(
      stubSelection([stubRange(text, text, rect)], "被划选的原文"),
      container,
    );
    expect({ ...rect }).toEqual({});
    expect(snapshot?.rect).toEqual({
      top: 160,
      left: 300,
      width: 50,
      height: 20,
      bottom: 180,
      right: 350,
    });
  });


  it("quotes selected text line by line and appends it after a blank line", () => {
    expect(buildQuotedDraftText("", "第一行\n第二行")).toBe("> 第一行\n> 第二行");
    expect(buildQuotedDraftText("已有草稿", "引用内容")).toBe("已有草稿\n\n> 引用内容");
    expect(buildQuotedDraftText("已有草稿   \n", "引用内容")).toBe("已有草稿\n\n> 引用内容");
    expect(buildQuotedDraftText("", "保留\r\n空行\n\n结尾")).toBe("> 保留\n> 空行\n>\n> 结尾");
    expect(buildQuotedDraftText("已有草稿", "  ")).toBe("已有草稿");
  });
});
