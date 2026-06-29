import { describe, expect, it } from "vitest";

import {
  captureTimelineScrollHeightAnchor,
  restoreTimelineScrollHeightAnchor,
} from "./timelineScrollAnchor";

describe("timeline scroll anchor", () => {
  it("keeps the same visible content after older messages are prepended", () => {
    const timeline = {
      scrollTop: 320,
      scrollHeight: 1200,
    };
    const anchor = captureTimelineScrollHeightAnchor(timeline);

    timeline.scrollHeight = 1680;
    restoreTimelineScrollHeightAnchor(timeline, anchor);

    expect(timeline.scrollTop).toBe(800);
  });

  it("ignores empty anchors", () => {
    const timeline = {
      scrollTop: 320,
      scrollHeight: 1200,
    };

    restoreTimelineScrollHeightAnchor(timeline, null);

    expect(timeline.scrollTop).toBe(320);
  });
});
