import { describe, expect, it } from "vitest";

import {
  captureConversationProcessScrollAnchor,
  restoreConversationProcessScrollAnchor,
} from "./conversationProcessScrollAnchor";

describe("conversationProcessScrollAnchor", () => {
  it("keeps the disclosure summary at the same viewport position after a row resize", () => {
    const timeline = {
      clientHeight: 434,
      scrollHeight: 5858,
      scrollTop: 5109.6,
    };
    let summaryTop = 190.6;
    const summary = {
      getBoundingClientRect: () => ({ top: summaryTop }),
    };
    const anchor = captureConversationProcessScrollAnchor(summary);

    summaryTop = 349.8;
    restoreConversationProcessScrollAnchor(timeline, summary, anchor);

    expect(timeline.scrollTop).toBeCloseTo(5268.8);
  });

  it("does not move the timeline when the summary stayed anchored", () => {
    const timeline = {
      clientHeight: 434,
      scrollHeight: 5858,
      scrollTop: 5109.6,
    };
    const summary = {
      getBoundingClientRect: () => ({ top: 190.6 }),
    };
    const anchor = captureConversationProcessScrollAnchor(summary);

    restoreConversationProcessScrollAnchor(timeline, summary, anchor);

    expect(timeline.scrollTop).toBe(5109.6);
  });
});
