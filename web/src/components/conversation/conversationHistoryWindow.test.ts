import { describe, expect, it } from "vitest";

import { shouldLoadEarlierConversationMessages } from "./conversationHistoryWindow";

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
