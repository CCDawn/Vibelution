import { describe, expect, it } from "vitest";

import {
  CONNECTION_FAILURE_PERSISTENCE_MS,
  CONNECTION_FAILURE_STREAK_THRESHOLD,
  EMPTY_HEALTH_FAILURE_STREAK,
  connectionNoticeVisible,
  nextHealthFailureStreak,
} from "./connectionHealthStreak";

function noticeVisible(streak: { count: number; startedAt: number }, failedAt: number): boolean {
  return connectionNoticeVisible({
    unavailable: true,
    failureCount: streak.count,
    failureStartedAt: streak.startedAt,
    failedAt,
    startupOverlayActive: false,
    shutdownOpen: false,
  });
}

describe("connection health failure streak", () => {
  it("keeps a single failed poll silent and only reports a persistent failure", () => {
    const first = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 1_000 });
    expect(first.count).toBe(1);
    expect(first.startedAt).toBe(1_000);
    expect(noticeVisible(first, 1_000)).toBe(false);

    const second = nextHealthFailureStreak(first, { healthy: false, errorAt: 6_000 });
    expect(second.count).toBe(CONNECTION_FAILURE_STREAK_THRESHOLD);
    expect(second.startedAt).toBe(1_000);
    // A 5s restart window is expected; it must not cover the page with a
    // "service disconnected" card.
    expect(noticeVisible(second, 6_000)).toBe(false);

    const persistent = nextHealthFailureStreak(second, { healthy: false, errorAt: 1_000 + CONNECTION_FAILURE_PERSISTENCE_MS });
    expect(noticeVisible(persistent, 1_000 + CONNECTION_FAILURE_PERSISTENCE_MS)).toBe(true);
  });

  it("keeps the first-failure clock across every failed poll in one outage", () => {
    const first = nextHealthFailureStreak(EMPTY_HEALTH_FAILURE_STREAK, { healthy: false, errorAt: 600_000 });
    const second = nextHealthFailureStreak(first, { healthy: false, errorAt: 605_000 });
    const third = nextHealthFailureStreak(second, { healthy: false, errorAt: 610_000 });
    expect(third.startedAt).toBe(600_000);
    expect(third.errorAt).toBe(610_000);
    expect(third.count).toBe(3);
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
    const visible = { unavailable: true, failureCount: 5, failureStartedAt: 1_000, failedAt: 60_000 };
    expect(connectionNoticeVisible({ ...visible, startupOverlayActive: true, shutdownOpen: false })).toBe(false);
    expect(connectionNoticeVisible({ ...visible, startupOverlayActive: false, shutdownOpen: true })).toBe(false);
    expect(connectionNoticeVisible({ ...visible, unavailable: false, startupOverlayActive: false, shutdownOpen: false })).toBe(false);
  });
});
