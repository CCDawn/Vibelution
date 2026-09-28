import { describe, expect, it } from "vitest";

import {
  COMPANION_ACTIVITY_ERROR_BACKOFF_STEPS_MS,
  COMPANION_ACTIVITY_NORMAL_POLL_MS,
  companionActivityFailureIntervalMs,
  createCompanionActivityRefreshState,
  resolveCompanionActivityRefetchInterval,
} from "./companionActivityRefreshPolicy";

interface QueryStateSnapshot {
  dataUpdatedAt: number;
  errorUpdatedAt: number;
}

function queryState(overrides: Partial<QueryStateSnapshot> = {}): QueryStateSnapshot {
  return {
    dataUpdatedAt: 0,
    errorUpdatedAt: 0,
    ...overrides,
  };
}

describe("companionActivityRefreshPolicy", () => {
  it("starts at the normal 5s cadence before any finished fetch", () => {
    const state = createCompanionActivityRefreshState();
    expect(resolveCompanionActivityRefetchInterval(state, queryState())).toBe(
      COMPANION_ACTIVITY_NORMAL_POLL_MS,
    );
  });

  it("climbs 30s 60s 120s 300s and caps at 300s on consecutive failures", () => {
    const state = createCompanionActivityRefreshState();
    const expectedLadder = [30_000, 60_000, 120_000, 300_000, 300_000];
    expectedLadder.forEach((expectedMs, index) => {
      expect(resolveCompanionActivityRefetchInterval(
        state,
        queryState({ errorUpdatedAt: 1_000 * (index + 1) }),
      )).toBe(expectedMs);
    });
    expect(state.consecutiveFailures).toBe(expectedLadder.length);
    expect(COMPANION_ACTIVITY_ERROR_BACKOFF_STEPS_MS).toHaveLength(4);
  });

  it("clears back to the normal 5s cadence after a success", () => {
    const state = createCompanionActivityRefreshState();
    resolveCompanionActivityRefetchInterval(state, queryState({ errorUpdatedAt: 1_000 }));
    resolveCompanionActivityRefetchInterval(state, queryState({ errorUpdatedAt: 2_000 }));
    expect(resolveCompanionActivityRefetchInterval(state, queryState())).toBe(60_000);
    expect(resolveCompanionActivityRefetchInterval(state, queryState({ dataUpdatedAt: 3_000 })))
      .toBe(COMPANION_ACTIVITY_NORMAL_POLL_MS);
    expect(state.consecutiveFailures).toBe(0);
  });

  it("stays on the current rung when re-invoked with unchanged timestamps", () => {
    const state = createCompanionActivityRefreshState();
    const failingState = queryState({ errorUpdatedAt: 1_000 });
    expect(resolveCompanionActivityRefetchInterval(state, failingState)).toBe(30_000);
    expect(resolveCompanionActivityRefetchInterval(state, failingState)).toBe(30_000);
    expect(state.consecutiveFailures).toBe(1);
  });

  it("counts a cached failure from before the current mount as the first failure", () => {
    const state = createCompanionActivityRefreshState();
    expect(resolveCompanionActivityRefetchInterval(state, queryState({ errorUpdatedAt: 500 })))
      .toBe(30_000);
  });

  it("lets the failure win the tie-break when one batch shows both a new error and a newer success", () => {
    const state = createCompanionActivityRefreshState();
    resolveCompanionActivityRefetchInterval(state, queryState({ dataUpdatedAt: 1_000 }));
    expect(resolveCompanionActivityRefetchInterval(
      state,
      queryState({ dataUpdatedAt: 3_000, errorUpdatedAt: 2_000 }),
    )).toBe(30_000);
  });

  it("maps failure levels onto the step table directly", () => {
    expect(companionActivityFailureIntervalMs(0)).toBe(COMPANION_ACTIVITY_NORMAL_POLL_MS);
    expect(companionActivityFailureIntervalMs(-1)).toBe(COMPANION_ACTIVITY_NORMAL_POLL_MS);
    expect(companionActivityFailureIntervalMs(1)).toBe(30_000);
    expect(companionActivityFailureIntervalMs(2)).toBe(60_000);
    expect(companionActivityFailureIntervalMs(3)).toBe(120_000);
    expect(companionActivityFailureIntervalMs(4)).toBe(300_000);
    expect(companionActivityFailureIntervalMs(99)).toBe(300_000);
  });
});
