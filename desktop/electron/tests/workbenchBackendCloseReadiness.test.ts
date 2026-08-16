import { describe, expect, it, vi } from "vitest";

import {
  isWorkbenchBackendSettledForWindowClose,
  waitForWorkbenchBackendSettledForWindowClose
} from "../src/lifecycle/workbenchBackendCloseReadiness.js";
import type { LauncherStatusSummary } from "../src/protocol/launcherControlClient.js";

function summary(overrides: Partial<LauncherStatusSummary> = {}): LauncherStatusSummary {
  return {
    overallState: "ready",
    observedState: "open",
    lifecycleConsistency: "consistent",
    phase: "steady",
    stateVersion: 1,
    backendHealthy: true,
    backendPortListening: true,
    lifecycleResults: [],
    ...overrides
  };
}

describe("isWorkbenchBackendSettledForWindowClose", () => {
  it("accepts a fully closed workbench", () => {
    expect(
      isWorkbenchBackendSettledForWindowClose(
        summary({
          observedState: "closed",
          phase: "steady",
          backendHealthy: false,
          backendPortListening: false
        })
      )
    ).toBe(true);
  });

  it("accepts the Electron handoff state after backend shutdown", () => {
    expect(
      isWorkbenchBackendSettledForWindowClose(
        summary({
          observedState: "partial",
          lifecycleConsistency: "external_window_owner_pending_ack",
          phase: "closing",
          backendHealthy: false,
          backendPortListening: false
        })
      )
    ).toBe(true);
  });

  it("accepts a closing workbench with backend offline even when consistency is stale", () => {
    expect(
      isWorkbenchBackendSettledForWindowClose(
        summary({
          observedState: "partial",
          lifecycleConsistency: "consistent",
          phase: "closing",
          backendHealthy: false,
          backendPortListening: false
        })
      )
    ).toBe(true);
  });

  it("rejects an open workbench that is still running", () => {
    expect(isWorkbenchBackendSettledForWindowClose(summary())).toBe(false);
  });

  it("rejects a partial workbench while the backend is still listening", () => {
    expect(
      isWorkbenchBackendSettledForWindowClose(
        summary({
          observedState: "partial",
          phase: "closing",
          backendHealthy: true,
          backendPortListening: true
        })
      )
    ).toBe(false);
  });
});

describe("waitForWorkbenchBackendSettledForWindowClose", () => {
  it("polls until the Electron handoff state appears", async () => {
    vi.useFakeTimers();
    const readStatus = vi
      .fn<() => Promise<LauncherStatusSummary>>()
      .mockResolvedValueOnce(summary())
      .mockResolvedValueOnce(
        summary({
          observedState: "partial",
          lifecycleConsistency: "external_window_owner_pending_ack",
          phase: "closing",
          backendHealthy: false,
          backendPortListening: false
        })
      );

    const promise = waitForWorkbenchBackendSettledForWindowClose({
      readStatus,
      timeoutMs: 5_000,
      pollIntervalMs: 1_000
    });

    await vi.advanceTimersByTimeAsync(1_000);
    await expect(promise).resolves.toBe(true);
    expect(readStatus).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("returns false when the backend never settles before the timeout", async () => {
    vi.useFakeTimers();
    const readStatus = vi.fn<() => Promise<LauncherStatusSummary>>().mockResolvedValue(summary());

    const promise = waitForWorkbenchBackendSettledForWindowClose({
      readStatus,
      timeoutMs: 2_000,
      pollIntervalMs: 1_000
    });

    await vi.advanceTimersByTimeAsync(2_000);
    await expect(promise).resolves.toBe(false);
    vi.useRealTimers();
  });
});
