// @vitest-environment happy-dom
import { describe, expect, it } from "vitest";

import {
  buildQuotedDraftText,
  extractConversationSelectionSnapshot,
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
  });

  it("anchors the menu above the selection and clamps it horizontally", () => {
    const position = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 160, left: 300, width: 50, height: 20, bottom: 180, right: 350 }),
      { top: 40, left: 0, width: 600, height: 800 },
    );
    expect(position.above).toBe(true);
    expect(position.top).toBe(120 - SELECTION_QUOTE_MENU_GAP_PX);
    expect(position.left).toBe(300);

    const clamped = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 130, left: 580, width: 50, height: 20, bottom: 150, right: 630 }),
      { top: 100, left: 0, width: 600, height: 800 },
    );
    expect(clamped.left).toBe(600 - 208);
  });

  it("flips below the selection when there is no headroom above", () => {
    const position = resolveSelectionQuoteMenuPosition(
      stubRect({ top: 100, left: 40, width: 50, height: 20, bottom: 120, right: 90 }),
      { top: 100, left: 0, width: 600, height: 800 },
    );
    expect(position.above).toBe(false);
    expect(position.top).toBe(20 + SELECTION_QUOTE_MENU_GAP_PX);
    expect(SELECTION_QUOTE_MENU_HEIGHT_PX).toBeGreaterThan(0);
  });


  it("quotes selected text line by line and appends it after a blank line", () => {
    expect(buildQuotedDraftText("", "第一行\n第二行")).toBe("> 第一行\n> 第二行");
    expect(buildQuotedDraftText("已有草稿", "引用内容")).toBe("已有草稿\n\n> 引用内容");
    expect(buildQuotedDraftText("已有草稿   \n", "引用内容")).toBe("已有草稿\n\n> 引用内容");
    expect(buildQuotedDraftText("", "保留\r\n空行\n\n结尾")).toBe("> 保留\n> 空行\n>\n> 结尾");
    expect(buildQuotedDraftText("已有草稿", "  ")).toBe("已有草稿");
  });
});
