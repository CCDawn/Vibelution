import { describe, expect, it, vi } from "vitest";

import { waitForWorkbenchLifecycleReady } from "../src/lifecycle/workbenchReadiness.js";

describe("waitForWorkbenchLifecycleReady", () => {
  it("waits for the accepted command result and a healthy backend before succeeding", async () => {
    const readStatus = vi
      .fn()
      .mockResolvedValueOnce({
        overallState: "starting",
        observedState: "closed",
        lifecycleConsistency: "consistent",
        backendHealthy: false,
        backendPortListening: false,
        lifecycleResults: []
      })
      .mockResolvedValueOnce({
        overallState: "partial",
        observedState: "partial",
        lifecycleConsistency: "browser_missing",
        backendHealthy: true,
        backendPortListening: true,
        lifecycleResults: [{ commandId: "cmd-1", completed: true, ok: true }]
      });

    const ready = await waitForWorkbenchLifecycleReady({
      commandId: "cmd-1",
      readStatus,
      timeoutMs: 100,
      pollIntervalMs: 0
    });

    expect(ready.observedState).toBe("partial");
    expect(readStatus).toHaveBeenCalledTimes(2);
  });

  it("does not accept a healthy stale backend before the matching command completes", async () => {
    const readStatus = vi
      .fn()
      .mockResolvedValueOnce({
        overallState: "ready",
        observedState: "open",
        lifecycleConsistency: "consistent",
        backendHealthy: true,
        backendPortListening: true,
        lifecycleResults: [{ commandId: "old-command", completed: true, ok: true }]
      })
      .mockResolvedValueOnce({
        overallState: "ready",
        observedState: "open",
        lifecycleConsistency: "consistent",
        backendHealthy: true,
        backendPortListening: true,
        lifecycleResults: [{ commandId: "cmd-rebuild", completed: true, ok: true }]
      });

    await waitForWorkbenchLifecycleReady({
      commandId: "cmd-rebuild",
      readStatus,
      timeoutMs: 100,
      pollIntervalMs: 0
    });

    expect(readStatus).toHaveBeenCalledTimes(2);
  });

  it("fails immediately when the matching lifecycle result is terminal and unsuccessful", async () => {
    const readStatus = vi.fn(async () => ({
      overallState: "error",
      observedState: "closed",
      lifecycleConsistency: "consistent",
      backendHealthy: false,
      backendPortListening: false,
      lifecycleResults: [{ commandId: "cmd-failed", completed: true, ok: false, message: "build failed" }]
    }));
    await expect(
      waitForWorkbenchLifecycleReady({
        commandId: "cmd-failed",
        readStatus,
        timeoutMs: 100,
        pollIntervalMs: 0
      })
    ).rejects.toThrow("build failed");
    expect(readStatus).toHaveBeenCalledTimes(1);
  });
});
