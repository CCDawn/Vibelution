import { describe, expect, it, beforeEach } from "vitest";

import {
  clearSessionTimelineScrollMemoryForTests,
  forgetSessionTimelineScroll,
  peekSessionTimelineScroll,
  rememberSessionTimelineScroll,
  restoreSessionTimelineScroll,
} from "./conversationSessionScrollMemory";

describe("conversationSessionScrollMemory", () => {
  beforeEach(() => {
    clearSessionTimelineScrollMemoryForTests();
  });

  it("remembers and peeks per-session scroll state", () => {
    rememberSessionTimelineScroll("s1", { scrollTop: 420, followingLatest: false });
    rememberSessionTimelineScroll("s2", { scrollTop: 0, followingLatest: true });

    expect(peekSessionTimelineScroll("s1")).toMatchObject({
      scrollTop: 420,
      followingLatest: false,
    });
    expect(peekSessionTimelineScroll("s2")?.followingLatest).toBe(true);
  });

  it("restores mid-history scroll without following the tail", () => {
    const timeline = { scrollHeight: 2000, clientHeight: 600, scrollTop: 0 };
    const result = restoreSessionTimelineScroll(timeline, {
      scrollTop: 900,
      followingLatest: false,
      savedAtMs: 1,
    });

    expect(result).toEqual({
      restored: true,
      scrollTop: 900,
      followingLatest: false,
    });
    expect(timeline.scrollTop).toBe(900);
  });

  it("clamps restored scrollTop to the current max viewport", () => {
    const timeline = { scrollHeight: 800, clientHeight: 600, scrollTop: 0 };
    const result = restoreSessionTimelineScroll(timeline, {
      scrollTop: 5000,
      followingLatest: false,
      savedAtMs: 1,
    });

    expect(result.restored).toBe(true);
    expect(result.scrollTop).toBe(200);
    expect(timeline.scrollTop).toBe(200);
  });

  it("followingLatest memory re-pins to the tail", () => {
    const timeline = { scrollHeight: 1800, clientHeight: 600, scrollTop: 12 };
    const result = restoreSessionTimelineScroll(timeline, {
      scrollTop: 12,
      followingLatest: true,
      savedAtMs: 1,
    });

    expect(result.restored).toBe(false);
    expect(result.followingLatest).toBe(true);
    expect(timeline.scrollTop).toBe(1200);
  });

  it("forgets deleted sessions", () => {
    rememberSessionTimelineScroll("gone", { scrollTop: 10, followingLatest: false });
    forgetSessionTimelineScroll("gone");
    expect(peekSessionTimelineScroll("gone")).toBeUndefined();
  });
});
