import { describe, expect, it, vi } from "vitest";

import { isRestartedBackendReady, waitForRestartedBackend } from "./workbenchRestartReadiness";

function healthResponse(pid: number, extra: Record<string, unknown> = {}): Response {
  return new Response(JSON.stringify({ status: "ok", pid, routesReady: true, shellReady: true, ...extra }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("workbench restart readiness", () => {
  it("rejects the draining backend and any backend that is not ready", () => {
    expect(isRestartedBackendReady(100, { status: "ok", pid: 100, routesReady: true, shellReady: true })).toBe(false);
    expect(isRestartedBackendReady(100, { status: "ok", pid: 101, routesReady: false, shellReady: true })).toBe(false);
    expect(isRestartedBackendReady(100, { status: "ok", pid: 101, routesReady: true, shellReady: false })).toBe(false);
    expect(isRestartedBackendReady(100, { status: "ok", pid: 101, routesReady: true, shellReady: true })).toBe(true);
  });

  it("accepts the first ready backend when recovery starts with no serving PID", () => {
    // The connection notice's recovery path runs while the backend is down;
    // there is no old PID to compare against, so waiting for a different one
    // would turn a successful recovery into a 120s timeout.
    expect(isRestartedBackendReady(0, { status: "ok", pid: 101, routesReady: true, shellReady: true })).toBe(true);
    expect(isRestartedBackendReady(0, { status: "ok", pid: 101, routesReady: false, shellReady: true })).toBe(false);
  });

  it("resolves only after a different ready PID is serving", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(healthResponse(100))
      .mockRejectedValueOnce(new Error("old backend closing"))
      .mockResolvedValueOnce(healthResponse(101, { shellReady: false }))
      .mockResolvedValueOnce(healthResponse(101));
    await expect(waitForRestartedBackend({
      previousPid: 100,
      intervalMs: 1,
      timeoutMs: 1_000,
      fetchImpl: fetchMock as unknown as typeof fetch,
    })).resolves.toEqual({ pid: 101 });
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("resolves a recovery as soon as the first ready backend appears", async () => {
    await expect(waitForRestartedBackend({
      previousPid: 0,
      intervalMs: 1,
      timeoutMs: 1_000,
      fetchImpl: vi.fn().mockResolvedValue(healthResponse(101)) as unknown as typeof fetch,
    })).resolves.toEqual({ pid: 101 });
  });

  it("stops when the restart was cancelled and times out without a replacement", async () => {
    await expect(waitForRestartedBackend({
      previousPid: 100,
      intervalMs: 1,
      timeoutMs: 1_000,
      fetchImpl: vi.fn().mockResolvedValue(healthResponse(100)) as unknown as typeof fetch,
      shouldContinue: () => false,
    })).rejects.toThrow("RESTART_WAIT_CANCELLED");

    await expect(waitForRestartedBackend({
      previousPid: 100,
      intervalMs: 1,
      timeoutMs: 10,
      fetchImpl: vi.fn().mockResolvedValue(healthResponse(100, { routesReady: false })) as unknown as typeof fetch,
    })).rejects.toThrow("RESTART_READY_TIMEOUT");
  });
});
