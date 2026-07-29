import { describe, expect, it } from "vitest";

import {
  captureConversationProcessScrollAnchor,
  restoreConversationProcessScrollAnchor,
} from "./conversationProcessScrollAnchor";

describe("conversationProcessScrollAnchor", () => {
  it("restores the disclosure summary to its pre-toggle viewport position", () => {
    const timeline = { scrollTop: 320 };
    let summaryTop = 180;
    const summary = {
      getBoundingClientRect: () => ({ top: summaryTop }),
    };
    const anchor = captureConversationProcessScrollAnchor(timeline, summary);

    timeline.scrollTop = 515;
    summaryTop = 112;
    restoreConversationProcessScrollAnchor(timeline, summary, anchor);

    expect(timeline.scrollTop).toBe(447);
  });

  it("does not produce a negative scroll position when restoring near the top", () => {
    const timeline = { scrollTop: 8 };
    let summaryTop = 20;
    const summary = {
      getBoundingClientRect: () => ({ top: summaryTop }),
    };
    const anchor = captureConversationProcessScrollAnchor(timeline, summary);

    summaryTop = -40;
    restoreConversationProcessScrollAnchor(timeline, summary, anchor);

    expect(timeline.scrollTop).toBe(0);
  });
});
