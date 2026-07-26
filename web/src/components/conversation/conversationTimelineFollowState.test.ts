import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  buildConversationHeightOffsets,
  findConversationIndexAtOffset,
  isTimelineNearBottom,
  recordConversationRowHeight,
  resolveConversationVirtualRange,
  resolveTimelineFollowState,
  shouldStickTimelineToBottomOnContentResize,
} from "./conversationTimelineFollowState";

describe("conversation timeline follow state", () => {
  it("keeps timeline follow helpers outside the React component file", () => {
    expect(conversationViewSource).toContain("from \"./conversationTimelineFollowState\"");
    expect(conversationViewSource).toContain("resolveTimelineFollowState({");
    expect(conversationViewSource).not.toContain("export function isTimelineNearBottom");
    expect(conversationViewSource).not.toContain("export function resolveTimelineFollowState");
    expect(conversationViewSource).not.toContain("type TimelineFollowStateInput");
    expect(conversationViewSource).not.toContain("type TimelineFollowState =");
  });

  it("treats positions within the bottom threshold as near bottom", () => {
    expect(isTimelineNearBottom({
      scrollHeight: 1200,
      clientHeight: 500,
      scrollTop: 668,
    })).toBe(true);
  });

  it("keeps following latest output when content growth alone moves the viewport away from bottom", () => {
    const state = resolveTimelineFollowState({
      scrollHeight: 1200,
      clientHeight: 500,
      scrollTop: 650,
      previousScrollTop: 650,
      wasFollowingLatest: true,
    });

    expect(state.isAtBottom).toBe(false);
    expect(state.shouldFollowLatest).toBe(true);
  });

  it("stops following latest output after an intentional upward scroll", () => {
    const state = resolveTimelineFollowState({
      scrollHeight: 1200,
      clientHeight: 500,
      scrollTop: 420,
      previousScrollTop: 650,
      wasFollowingLatest: true,
    });

    expect(state.isAtBottom).toBe(false);
    expect(state.shouldFollowLatest).toBe(false);
  });

  it("resumes following latest output when the user returns near the bottom", () => {
    const state = resolveTimelineFollowState({
      scrollHeight: 1200,
      clientHeight: 500,
      scrollTop: 688,
      previousScrollTop: 420,
      wasFollowingLatest: false,
    });

    expect(state.isAtBottom).toBe(true);
    expect(state.shouldFollowLatest).toBe(true);
  });

  it("sticks to bottom on content resize only while following latest", () => {
    expect(shouldStickTimelineToBottomOnContentResize({
      autoScrollToLatest: true,
      followingLatest: true,
    })).toBe(true);
    expect(shouldStickTimelineToBottomOnContentResize({
      autoScrollToLatest: true,
      followingLatest: false,
    })).toBe(false);
  });

  it("uses measured height prefix sums for spacers (D2)", () => {
    const heights = [100, 200, 150, 80];
    const offsets = buildConversationHeightOffsets(heights);
    expect(offsets).toEqual([0, 100, 300, 450, 530]);
    expect(findConversationIndexAtOffset(offsets, 0)).toBe(0);
    expect(findConversationIndexAtOffset(offsets, 100)).toBe(1);
    expect(findConversationIndexAtOffset(offsets, 299)).toBe(1);
    expect(findConversationIndexAtOffset(offsets, 450)).toBe(3);

    const mid = resolveConversationVirtualRange({
      itemCount: 40,
      scrollTop: 1200,
      viewportHeight: 600,
      followingLatest: false,
      heights: Array.from({ length: 40 }, () => 100),
      overscan: 1,
    });
    expect(mid.start).toBeGreaterThan(0);
    expect(mid.end).toBeLessThan(40);
    expect(mid.topSpacerPx).toBe(mid.start * 100);
    expect(mid.bottomSpacerPx).toBe((40 - mid.end) * 100);
    expect(mid.totalHeightPx).toBe(4000);

    const tail = resolveConversationVirtualRange({
      itemCount: 80,
      scrollTop: 0,
      viewportHeight: 600,
      followingLatest: true,
      heights: Array.from({ length: 80 }, () => 100),
      overscan: 2,
    });
    expect(tail.end).toBe(80);
    expect(tail.bottomSpacerPx).toBe(0);
    expect(tail.start).toBeGreaterThan(0);
  });

  it("records row heights only when they change", () => {
    const cache = new Map<string, number>();
    expect(recordConversationRowHeight(cache, "r1", 120.4)).toBe(true);
    expect(cache.get("r1")).toBe(120);
    expect(recordConversationRowHeight(cache, "r1", 120)).toBe(false);
    expect(recordConversationRowHeight(cache, "", 50)).toBe(false);
  });
});
