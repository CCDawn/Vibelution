import { describe, expect, it } from "vitest";

import {
  CONNECTION_FAILURE_STREAK_THRESHOLD,
  EMPTY_HEALTH_FAILURE_STREAK,
  connectionNoticeVisible,
  nextHealthFailureStreak,
} from "./connectionHealthStreak";

describe("connection health failure streak", () => {
  it("keeps a single failed poll silent and only reports a repeated failure", () => {
    const first = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 1_000 });
    expect(first.count).toBe(1);
    expect(connectionNoticeVisible({ unavailable: true, failureCount: first.count, startupOverlayActive: false, shutdownOpen: false })).toBe(false);

    const second = nextHealthFailureStreak(first, { healthy: false, errorAt: 6_000 });
    expect(second.count).toBe(CONNECTION_FAILURE_STREAK_THRESHOLD);
    expect(connectionNoticeVisible({ unavailable: true, failureCount: second.count, startupOverlayActive: false, shutdownOpen: false })).toBe(true);
  });

  it("does not inflate the streak when the same failed poll is observed twice", () => {
    const first = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 1_000 });
    const repeated = nextHealthFailureStreak(first, { healthy: false, errorAt: 1_000 });
    expect(repeated).toBe(first);
    expect(repeated.count).toBe(1);
  });

  it("resets on a recovered poll so a later failure starts a fresh streak", () => {
    const failed = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 1_000 });
    const healthy = nextHealthFailureStreak(failed, { healthy: true, errorAt: 6_000 });
    expect(healthy).toEqual(EMPTY_HEALTH_FAILURE_STREAK);
    const laterFailure = nextHealthFailureStreak(healthy, { healthy: false, errorAt: 11_000 });
    expect(laterFailure.count).toBe(1);
  });

  it("ignores failures without a stamp instead of guessing a streak", () => {
    const first = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 0 });
    expect(first).toBe(EMPTY_HEALTH_FAILURE_STREAK);
  });

  it("stays hidden while startup or shutdown owns the screen", () => {
    expect(connectionNoticeVisible({ unavailable: true, failureCount: 5, startupOverlayActive: true, shutdownOpen: false })).toBe(false);
    expect(connectionNoticeVisible({ unavailable: true, failureCount: 5, startupOverlayActive: false, shutdownOpen: true })).toBe(false);
    expect(connectionNoticeVisible({ unavailable: false, failureCount: 5, startupOverlayActive: false, shutdownOpen: false })).toBe(false);
  });
});
