import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  isTimelineNearBottom,
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

  it("virtualizes long timelines with tail focus while following latest", () => {
    const full = resolveConversationVirtualRange({
      itemCount: 12,
      scrollTop: 0,
      viewportHeight: 600,
      followingLatest: true,
    });
    expect(full.start).toBe(0);
    expect(full.end).toBe(12);

    const tail = resolveConversationVirtualRange({
      itemCount: 80,
      scrollTop: 0,
      viewportHeight: 600,
      followingLatest: true,
      estimatePx: 100,
      overscan: 2,
    });
    expect(tail.end).toBe(80);
    expect(tail.start).toBeGreaterThan(0);
    expect(tail.topSpacerPx).toBe(tail.start * 100);
    expect(tail.bottomSpacerPx).toBe(0);
  });
});
