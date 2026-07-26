import { describe, expect, it } from "vitest";

import {
  INITIAL_VISIBLE_MESSAGE_COUNT,
  MAX_CLIENT_VISIBLE_MESSAGE_COUNT,
  nextVisibleMessageLimit,
  resolveVisibleMessageCount,
  shouldLoadEarlierConversationMessages,
  shouldPreferServerEarlierLoad,
  TIMELINE_HISTORY_LOAD_BATCH_COUNT,
} from "./conversationHistoryWindow";

describe("conversation history window loading", () => {
  it("loads earlier messages when hidden history exists but the current window cannot scroll upward", () => {
    expect(shouldLoadEarlierConversationMessages({
      clientHeight: 720,
      hiddenMessageCount: 8,
      previousScrollTop: 0,
      scrollHeight: 640,
      scrollTop: 0,
      thresholdPx: 56,
    })).toBe(true);
  });

  it("loads earlier messages when the timeline is already pinned at the top edge", () => {
    expect(shouldLoadEarlierConversationMessages({
      clientHeight: 720,
      hiddenMessageCount: 8,
      previousScrollTop: 0,
      scrollHeight: 1200,
      scrollTop: 0,
      thresholdPx: 56,
    })).toBe(true);
  });

  it("keeps the existing upward top-edge scroll trigger for scrollable timelines", () => {
    expect(shouldLoadEarlierConversationMessages({
      clientHeight: 720,
      hiddenMessageCount: 8,
      previousScrollTop: 80,
      scrollHeight: 1200,
      scrollTop: 48,
      thresholdPx: 56,
    })).toBe(true);
  });

  it("does not load history away from the top edge or when there is no hidden history", () => {
    expect(shouldLoadEarlierConversationMessages({
      clientHeight: 720,
      hiddenMessageCount: 8,
      previousScrollTop: 180,
      scrollHeight: 1600,
      scrollTop: 120,
      thresholdPx: 56,
    })).toBe(false);
    expect(shouldLoadEarlierConversationMessages({
      clientHeight: 720,
      hiddenMessageCount: 0,
      previousScrollTop: 0,
      scrollHeight: 640,
      scrollTop: 0,
      thresholdPx: 56,
    })).toBe(false);
  });
});

describe("conversation timeline window policy (U5)", () => {
  it("starts with a compact initial window and batch size", () => {
    expect(INITIAL_VISIBLE_MESSAGE_COUNT).toBe(12);
    expect(TIMELINE_HISTORY_LOAD_BATCH_COUNT).toBe(12);
    expect(MAX_CLIENT_VISIBLE_MESSAGE_COUNT).toBeGreaterThanOrEqual(INITIAL_VISIBLE_MESSAGE_COUNT * 4);
  });

  it("grows the client window by batch until the display count", () => {
    expect(nextVisibleMessageLimit({
      currentLimit: 12,
      displayMessageCount: 40,
    })).toBe(24);
    expect(nextVisibleMessageLimit({
      currentLimit: 36,
      displayMessageCount: 40,
    })).toBe(40);
    expect(nextVisibleMessageLimit({
      currentLimit: 68,
      displayMessageCount: 200,
    })).toBe(80);
  });

  it("resolves rendered count as min(display, limit)", () => {
    expect(resolveVisibleMessageCount({
      displayMessageCount: 5,
      visibleLimit: 12,
    })).toBe(5);
    expect(resolveVisibleMessageCount({
      displayMessageCount: 100,
      visibleLimit: 12,
    })).toBe(12);
  });

  it("prefers server earlier-load when the soft DOM ceiling is reached", () => {
    expect(shouldPreferServerEarlierLoad({
      visibleMessageCount: 72,
      displayMessageCount: 120,
      hasEarlierMessages: true,
      earlierMessagesLoading: false,
    })).toBe(true);
    expect(shouldPreferServerEarlierLoad({
      visibleMessageCount: 24,
      displayMessageCount: 40,
      hasEarlierMessages: true,
      earlierMessagesLoading: false,
    })).toBe(false);
    expect(shouldPreferServerEarlierLoad({
      visibleMessageCount: 72,
      displayMessageCount: 120,
      hasEarlierMessages: false,
      earlierMessagesLoading: false,
    })).toBe(false);
  });
});
