import { describe, expect, it } from "vitest";

import {
  buildConversationTurnNavDirectory,
  CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS,
  CONVERSATION_TURN_NAV_LABEL_MAX_CHARS,
  CONVERSATION_TURN_NAV_MIN_TURNS,
  CONVERSATION_TURN_NAV_USER_PREVIEW_MAX_CHARS,
  conversationTurnNavLabel,
  conversationTurnNavRowKind,
  resolveConversationTurnNavCurrentIndex,
  type ConversationTurnNavEntry,
  type ConversationTurnNavRowInput,
} from "./conversationTurnNavigation";

function rows(...specs: Array<[rowKey: string, previewText?: string]>): ConversationTurnNavRowInput[] {
  return specs.map(([rowKey, previewText = ""]) => ({ rowKey, previewText }));
}

function turnDirectory(): ConversationTurnNavEntry[] {
  return buildConversationTurnNavDirectory(rows(
    ["lifecycle:boot", "已启动"],
    ["user-message:u1", "第一轮提问"],
    ["assistant-turn:t1", "第一轮回答"],
    ["user-submission:sub-2", "第二轮\n多行 提问"],
    ["assistant-turn:t2", "第二轮回答"],
    ["assistant-turn:t3", "孤儿回答一"],
    ["user-message:u4"],
  ), { fallbackLabel: (turnNumber) => `第 ${turnNumber} 轮` });
}

describe("conversationTurnNavigation", () => {
  it("classifies timeline row keys into user, assistant, and other", () => {
    expect(conversationTurnNavRowKind("user-message:u1")).toBe("user");
    expect(conversationTurnNavRowKind("user-submission:sub-1")).toBe("user");
    expect(conversationTurnNavRowKind("assistant-turn:t1")).toBe("assistant");
    expect(conversationTurnNavRowKind("assistant-active:render-1")).toBe("assistant");
    expect(conversationTurnNavRowKind("assistant-submission:sub-2")).toBe("assistant");
    expect(conversationTurnNavRowKind("cli-agent-lifecycle:boot")).toBe("other");
    expect(conversationTurnNavRowKind("")).toBe("other");
  });

  it("groups user rows plus the following assistant row into turns and skips chrome rows", () => {
    const entries = turnDirectory();
    expect(entries.map((entry) => [entry.anchorRowIndex, entry.userRowKey, entry.assistantRowKey])).toEqual([
      [1, "user-message:u1", "assistant-turn:t1"],
      [3, "user-submission:sub-2", "assistant-turn:t2"],
      [5, null, "assistant-turn:t3"],
      [6, "user-message:u4", null],
    ]);
    expect(entries.map((entry) => entry.turnIndex)).toEqual([0, 1, 2, 3]);
  });

  it("labels turns from the user preview and falls back to the localized turn number", () => {
    const entries = turnDirectory();
    expect(entries[0]?.label).toBe("第一轮提问");
    expect(entries[1]?.label).toBe("第二轮 多行 提问");
    expect(entries[2]?.label).toBe("孤儿回答一");
    expect(entries[3]?.label).toBe("第 4 轮");
  });

  it("keeps previews empty without a lookup map (backward compatible)", () => {
    for (const entry of turnDirectory()) {
      expect(entry.userPreviewText).toBe("");
      expect(entry.assistantPreviewText).toBe("");
    }
  });

  it("carries clamped user and assistant previews when a lookup map is given", () => {
    const longUserText = "用户长消息 ".repeat(60);
    const entries = buildConversationTurnNavDirectory(rows(
      ["lifecycle:boot", "已启动"],
      ["user-message:u1", "第一轮提问"],
      ["assistant-turn:t1", "第一轮回答"],
      ["assistant-turn:t3", "孤儿回答"],
    ), {
      fallbackLabel: (turnNumber) => `第 ${turnNumber} 轮`,
      previewTextByRowKey: new Map([
        ["user-message:u1", longUserText],
        ["assistant-turn:t1", "回答\n第二段\t文本"],
        ["assistant-turn:t3", "   "],
      ]),
    });
    expect(entries[0]?.userPreviewText).toHaveLength(CONVERSATION_TURN_NAV_USER_PREVIEW_MAX_CHARS);
    expect(entries[0]?.userPreviewText.startsWith("用户长消息")).toBe(true);
    expect(entries[0]?.assistantPreviewText).toBe("回答 第二段 文本");
    // Assistant-anchored turn: no user preview; blank lookup stays empty.
    expect(entries[1]?.userPreviewText).toBe("");
    expect(entries[1]?.assistantPreviewText).toBe("");
    // Labels keep coming from the row plan, not the preview map.
    expect(entries[0]?.label).toBe("第一轮提问");
  });

  it("clamps assistant previews to their own cap without touching the user cap", () => {
    const longAssistantText = "x".repeat(CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS + 40);
    const entries = buildConversationTurnNavDirectory(rows(
      ["user-message:u1", "问"],
      ["assistant-turn:t1", "答"],
    ), {
      previewTextByRowKey: new Map([
        ["user-message:u1", "短问"],
        ["assistant-turn:t1", longAssistantText],
      ]),
    });
    expect(entries[0]?.userPreviewText).toBe("短问");
    expect(entries[0]?.assistantPreviewText).toHaveLength(CONVERSATION_TURN_NAV_ASSISTANT_PREVIEW_MAX_CHARS);
  });

  it("caps labels to a single line of bounded length", () => {
    expect(conversationTurnNavLabel("  a\n b\t c  ", "fallback")).toBe("a b c");
    expect(conversationTurnNavLabel("   ", "fallback")).toBe("fallback");
    expect(conversationTurnNavLabel("x".repeat(CONVERSATION_TURN_NAV_LABEL_MAX_CHARS + 20), "f"))
      .toHaveLength(CONVERSATION_TURN_NAV_LABEL_MAX_CHARS);
  });

  it("resolves the current turn from the probe offset inside the virtual segment", () => {
    const entries = turnDirectory();
    const rowIndexAtOffset = (offset: number) => {
      // Turn anchors sit at rows 1/3/5/6; each turn spans ~200px.
      return Math.min(6, Math.floor(offset / 200));
    };
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 7,
      historyTotalSize: 1400,
      scrollOffset: 0,
      viewportHeight: 600,
      rowIndexAtOffset,
    })).toBe(0);
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 7,
      historyTotalSize: 1400,
      scrollOffset: 800,
      viewportHeight: 600,
      rowIndexAtOffset,
    })).toBe(2);
    // Probe inside the last turn before the live tail resolves to it.
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 7,
      historyTotalSize: 1400,
      scrollOffset: 1200,
      viewportHeight: 600,
      rowIndexAtOffset,
    })).toBe(3);
  });

  it("treats the live tail and beyond-virtual probes as the last entry", () => {
    const entries = turnDirectory();
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 6,
      historyTotalSize: 1200,
      scrollOffset: 1100,
      viewportHeight: 600,
      rowIndexAtOffset: () => null,
    })).toBe(entries.length - 1);
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 6,
      historyTotalSize: 1200,
      scrollOffset: 1200,
      viewportHeight: 600,
      rowIndexAtOffset: () => 6,
    })).toBe(entries.length - 1);
  });

  it("degrades to the first entry for unresolved probes and to -1 without turns", () => {
    const entries = turnDirectory();
    expect(resolveConversationTurnNavCurrentIndex({
      entries,
      historyRowCount: 6,
      historyTotalSize: 1200,
      scrollOffset: 100,
      viewportHeight: 600,
      rowIndexAtOffset: () => null,
    })).toBe(0);
    expect(resolveConversationTurnNavCurrentIndex({
      entries: [],
      historyRowCount: 0,
      historyTotalSize: 0,
      scrollOffset: 0,
      viewportHeight: 600,
      rowIndexAtOffset: () => null,
    })).toBe(-1);
  });

  it("keeps the minimap gated behind a six-turn minimum", () => {
    expect(CONVERSATION_TURN_NAV_MIN_TURNS).toBe(6);
    expect(turnDirectory()).toHaveLength(4);
  });
});
