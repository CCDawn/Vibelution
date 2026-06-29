import { describe, expect, it } from "vitest";

import {
  captureTimelineScrollHeightAnchor,
  captureTimelineRowKeyAnchor,
  restoreTimelineScrollHeightAnchor,
  restoreTimelineRowKeyAnchor,
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

  it("restores a visible row by row key and offset after prepended content changes height", () => {
    const rowElements = [
      rowElement("row-1", 92),
      rowElement("row-2", 180),
      rowElement("row-3", 260),
    ];
    const timeline = timelineElement(rowElements, 100, 320, 1200);
    const anchor = captureTimelineRowKeyAnchor(timeline);

    expect(anchor).toMatchObject({ rowKey: "row-2", offsetTop: 80 });

    rowElements[1].top = 520;
    restoreTimelineRowKeyAnchor(timeline, anchor);

    expect(timeline.scrollTop).toBe(660);
  });

  it("falls back to scroll height when the row-key anchor is no longer in the DOM", () => {
    const timeline = timelineElement([rowElement("row-1", 160)], 100, 320, 1200);
    const anchor = {
      rowKey: "row-2",
      offsetTop: 80,
      heightAnchor: { scrollTop: 320, scrollHeight: 1200 },
    };

    timeline.scrollHeight = 1500;
    restoreTimelineRowKeyAnchor(timeline, anchor);

    expect(timeline.scrollTop).toBe(620);
  });
});

function rowElement(rowKey: string, top: number) {
  return {
    top,
    dataset: { conversationRowKey: rowKey },
    getBoundingClientRect() {
      return { top: this.top };
    },
  };
}

function timelineElement(
  rowElements: ReturnType<typeof rowElement>[],
  top: number,
  scrollTop: number,
  scrollHeight: number,
) {
  return {
    scrollTop,
    scrollHeight,
    getBoundingClientRect() {
      return { top };
    },
    querySelectorAll(selector: string) {
      return selector === "[data-conversation-row-key]" ? rowElements : [];
    },
  };
}
