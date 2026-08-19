import { describe, expect, it, vi } from "vitest";

import {
  RECONCILE_DEADLINE_MAX_DELAY_MS,
  RECONCILE_DEADLINE_MIN_DELAY_MS,
  clampReconcileDeadlineDelayMs,
  createReconcileDeadlineScheduler,
} from "../src/state/reconcileDeadlineScheduler.js";

describe("reconcileDeadlineScheduler", () => {
  it("clamps past, far-future, and invalid deadlines", () => {
    const now = Date.parse("2026-08-19T06:00:00.000Z");
    expect(clampReconcileDeadlineDelayMs("2026-08-19T05:59:50.000Z", now)).toBe(RECONCILE_DEADLINE_MIN_DELAY_MS);
    expect(clampReconcileDeadlineDelayMs("2026-08-19T07:00:00.000Z", now)).toBe(RECONCILE_DEADLINE_MAX_DELAY_MS);
    expect(clampReconcileDeadlineDelayMs("2026-08-19T06:00:10.000Z", now)).toBe(10_000);
    expect(clampReconcileDeadlineDelayMs("not-a-date", now)).toBeNull();
    expect(clampReconcileDeadlineDelayMs("", now)).toBeNull();
  });

  it("fires once on the deadline and does not keep old facts", () => {
    vi.useFakeTimers();
    try {
      const onDue = vi.fn();
      const scheduler = createReconcileDeadlineScheduler({ onDue });
      scheduler.schedule("2026-08-19T06:00:10.000Z", Date.parse("2026-08-19T06:00:00.000Z"));
      vi.advanceTimersByTime(9_999);
      expect(onDue).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(onDue).toHaveBeenCalledTimes(1);
      scheduler.schedule("2026-08-19T06:00:20.000Z", Date.parse("2026-08-19T06:00:10.000Z"));
      vi.advanceTimersByTime(10_000);
      expect(onDue).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("replaces the previous timer when a new payload arrives and clears on exit", () => {
    vi.useFakeTimers();
    try {
      const onDue = vi.fn();
      const scheduler = createReconcileDeadlineScheduler({ onDue });
      scheduler.schedule("2026-08-19T06:00:10.000Z", Date.parse("2026-08-19T06:00:00.000Z"));
      scheduler.schedule("2026-08-19T06:00:04.000Z", Date.parse("2026-08-19T06:00:00.000Z"));
      vi.advanceTimersByTime(4_000);
      expect(onDue).toHaveBeenCalledTimes(1);
      scheduler.clear();
      scheduler.schedule("2026-08-19T06:00:20.000Z", Date.parse("2026-08-19T06:00:10.000Z"));
      scheduler.clear();
      vi.advanceTimersByTime(20_000);
      expect(onDue).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });
});
