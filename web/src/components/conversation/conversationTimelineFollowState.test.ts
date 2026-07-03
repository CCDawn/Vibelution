import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  isTimelineNearBottom,
  resolveTimelineFollowState,
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
});
