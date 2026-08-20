import { describe, expect, it, vi } from "vitest";

import {
  ISOLATED_INSTANCE_READY_WAIT_MS,
  resolveIsolatedReadyTimeoutMs,
  superviseIsolatedInstanceStart,
} from "../src/process/isolatedInstanceSupervisor.js";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";

function currentLease(generation: number) {
  const supervisor = new LauncherLifecycleSupervisor();
  const intent = supervisor.beginIntent({
    instanceId: "worktree:task",
    operation: "start",
    desiredState: "open",
    generation,
  });
  const lease = supervisor.bindCommand(intent, { commandId: `cmd-${generation}`, generation });
  if (lease === null) {
    throw new Error("expected current isolated lease");
  }
  return { supervisor, lease };
}

describe("superviseIsolatedInstanceStart", () => {
  it("uses a 180s isolated ready wait only as the claim budget fallback", () => {
    expect(ISOLATED_INSTANCE_READY_WAIT_MS).toBe(180_000);
    expect(
      resolveIsolatedReadyTimeoutMs({
        deadlineAt: "2026-08-20T12:03:00Z",
        nowMs: Date.parse("2026-08-20T12:00:00Z"),
      })
    ).toBe(180_000);
    expect(
      resolveIsolatedReadyTimeoutMs({
        deadlineAt: "2026-08-20T12:00:00Z",
        nowMs: Date.parse("2026-08-20T12:02:30Z"),
      })
    ).toBe(1);
  });

  it("opens the window and marks ready after HTTP succeeds", async () => {
    const { supervisor, lease } = currentLease(4);
    const waitForHttp = vi.fn().mockResolvedValue(undefined);
    const openWindow = vi.fn().mockResolvedValue(undefined);
    const markReady = vi.fn().mockResolvedValue(undefined);
    const markError = vi.fn();
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: (candidate) => supervisor.completeReady(candidate),
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded: async () => undefined,
      closeWindowAfterReadyFailure: async () => undefined,
      timeoutMs: 50,
      waitForHttp,
      openWindow,
      markReady,
      markError,
    });
    expect(result).toBe("opened");
    expect(waitForHttp).toHaveBeenCalledWith("http://127.0.0.1:8003/", 50, lease.signal);
    expect(openWindow).toHaveBeenCalledTimes(1);
    expect(markReady).toHaveBeenCalledWith(4);
    expect(markError).not.toHaveBeenCalled();
    expect(supervisor.snapshot("worktree:task")?.phase).toBe("ready");
  });

  it("writes observe-error for the same generation when HTTP times out", async () => {
    const { supervisor, lease } = currentLease(7);
    const markError = vi.fn().mockResolvedValue(undefined);
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: (candidate) => supervisor.completeReady(candidate),
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded: async () => undefined,
      closeWindowAfterReadyFailure: async () => undefined,
      timeoutMs: 10,
      waitForHttp: async () => {
        throw new Error("workbench HTTP was not reachable");
      },
      openWindow: async () => {
        throw new Error("should not open");
      },
      markReady: async () => undefined,
      markError,
    });
    expect(result).toBe("error");
    expect(markError).toHaveBeenCalledWith(7, "workbench HTTP was not reachable");
  });

  it("ignores a stale observer that resolves after a newer generation", async () => {
    const { supervisor, lease } = currentLease(8);
    const openWindow = vi.fn();
    const markReady = vi.fn();
    const markError = vi.fn();
    const waitForHttp = vi.fn(async () => {
      supervisor.beginIntent({
        instanceId: "worktree:task",
        operation: "stop",
        desiredState: "closed",
      });
    });

    await expect(superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: (candidate) => supervisor.completeReady(candidate),
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded: async () => undefined,
      closeWindowAfterReadyFailure: async () => undefined,
      timeoutMs: 50,
      waitForHttp,
      openWindow,
      markReady,
      markError,
    })).resolves.toBe("ignored");

    expect(openWindow).not.toHaveBeenCalled();
    expect(markReady).not.toHaveBeenCalled();
    expect(markError).not.toHaveBeenCalled();
  });

  it("closes a window opened by a start that is superseded by stop during the open call", async () => {
    const { supervisor, lease } = currentLease(9);
    const closeWindowIfSuperseded = vi.fn(async () => undefined);
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: (candidate) => supervisor.completeReady(candidate),
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded,
      closeWindowAfterReadyFailure: async () => undefined,
      timeoutMs: 50,
      waitForHttp: async () => undefined,
      openWindow: async () => {
        supervisor.beginIntent({
          instanceId: "worktree:task",
          operation: "stop",
          desiredState: "closed"
        });
      },
      markReady: async () => undefined,
      markError: async () => undefined
    });

    expect(result).toBe("ignored");
    expect(closeWindowIfSuperseded).toHaveBeenCalledOnce();
  });

  it("closes and reports an observer error when READY completion violates the current lease", async () => {
    const { supervisor, lease } = currentLease(10);
    const closeWindowAfterReadyFailure = vi.fn(async () => undefined);
    const markError = vi.fn(async () => undefined);
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: () => false,
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded: async () => undefined,
      closeWindowAfterReadyFailure,
      timeoutMs: 50,
      waitForHttp: async () => undefined,
      openWindow: async () => undefined,
      markReady: async () => undefined,
      markError
    });

    expect(result).toBe("error");
    expect(closeWindowAfterReadyFailure).toHaveBeenCalledOnce();
    expect(markError).toHaveBeenCalledWith(10, "isolated lifecycle READY completion failed for worktree:task");
  });

  it("renews the owner lease while waiting for HTTP", async () => {
    const { supervisor, lease } = currentLease(11);
    const renewLease = vi.fn().mockResolvedValue(undefined);
    await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      lease,
      isCurrent: (candidate) => supervisor.isCurrent(candidate),
      claimReady: (candidate) => supervisor.claimReady(candidate),
      completeReady: (candidate) => supervisor.completeReady(candidate),
      releaseReadyClaim: (candidate) => supervisor.releaseReadyClaim(candidate),
      closeWindowIfSuperseded: async () => undefined,
      closeWindowAfterReadyFailure: async () => undefined,
      timeoutMs: 40,
      heartbeatMs: 10,
      waitForHttp: async () => {
        await new Promise((resolve) => setTimeout(resolve, 35));
      },
      openWindow: async () => undefined,
      markReady: async () => undefined,
      markError: async () => undefined,
      renewLease
    });
    expect(renewLease.mock.calls.length).toBeGreaterThan(1);
  });
});
