import { describe, expect, it, vi } from "vitest";
import { ensureWorkbenchBackendReady } from "../src/windows/workbenchOpenBackendGate.js";

const WORKSPACE_ROOT = "C:/tmp/fake-workspace";
const WORKBENCH_URL = "http://127.0.0.1:8000/";

function baseInput(overrides: Partial<Parameters<typeof ensureWorkbenchBackendReady>[0]> = {}) {
  return {
    workspaceRoot: WORKSPACE_ROOT,
    workbenchUrl: WORKBENCH_URL,
    isBackendHealthy: async () => true,
    ...overrides
  };
}

describe("ensureWorkbenchBackendReady", () => {
  it("opens with zero extra actions when the backend is already healthy", async () => {
    const isBackendReachable = vi.fn(async () => true);
    const startLifecycle = vi.fn(async () => ({ accepted: true }));
    const waitForHealthy = vi.fn(async () => undefined);

    const result = await ensureWorkbenchBackendReady(baseInput({
      isBackendReachable,
      startLifecycle,
      waitForHealthy
    }));

    expect(result).toEqual({ started: false });
    expect(isBackendReachable).toHaveBeenCalledWith(WORKSPACE_ROOT);
    expect(startLifecycle).not.toHaveBeenCalled();
    expect(waitForHealthy).not.toHaveBeenCalled();
  });

  it("starts the backend through the existing lifecycle path when it is down", async () => {
    const isBackendReachable = vi.fn(async () => false);
    const startLifecycle = vi.fn(async () => ({ accepted: true }));
    const waitForHealthy = vi.fn(async () => undefined);

    const result = await ensureWorkbenchBackendReady(baseInput({
      isBackendReachable,
      startLifecycle,
      waitForHealthy
    }));

    expect(result).toEqual({ started: true });
    expect(startLifecycle).toHaveBeenCalledTimes(1);
    expect(waitForHealthy).toHaveBeenCalledWith({
      url: WORKBENCH_URL,
      timeoutMs: expect.any(Number)
    });
    expect(waitForHealthy.mock.calls[0][0].timeoutMs).toBeGreaterThan(0);
  });

  it("recovers an alive listener whose health is not ready", async () => {
    const startLifecycle = vi.fn(async () => undefined);
    const waitForHealthy = vi.fn(async () => undefined);
    await expect(ensureWorkbenchBackendReady(baseInput({
      isBackendReachable: async () => true,
      isBackendHealthy: async () => false,
      startLifecycle,
      waitForHealthy
    }))).resolves.toEqual({ started: true });
    expect(startLifecycle).toHaveBeenCalledOnce();
    expect(waitForHealthy).toHaveBeenCalledOnce();
  });

  it.each([
    { status: "ok", routesReady: false, workspaceRoot: WORKSPACE_ROOT },
    { status: "ok", routesReady: true, workspaceRoot: "C:/another-workspace" }
  ])("rejects unready or foreign-workspace health before reuse", async (body) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body))));
    try {
      const startLifecycle = vi.fn(async () => undefined);
      await ensureWorkbenchBackendReady(baseInput({
        isBackendReachable: async () => true,
        isBackendHealthy: undefined,
        startLifecycle,
        waitForHealthy: async () => undefined
      }));
      expect(startLifecycle).toHaveBeenCalledOnce();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("clears the start timer and shares the remaining budget with health", async () => {
    vi.useFakeTimers();
    try {
      const waitForHealthy = vi.fn(async () => undefined);
      const pending = ensureWorkbenchBackendReady(baseInput({
        isBackendReachable: async () => false,
        startLifecycle: () => new Promise((resolve) => setTimeout(resolve, 600)),
        waitForHealthy,
        startWaitTimeoutMs: 1_000
      }));
      await vi.advanceTimersByTimeAsync(600);
      await pending;
      expect(waitForHealthy).toHaveBeenCalledWith({ url: WORKBENCH_URL, timeoutMs: 400 });
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it("propagates a failed lifecycle start instead of waiting forever", async () => {
    const isBackendReachable = vi.fn(async () => false);
    const startLifecycle = vi.fn(async () => {
      throw new Error("lifecycle start was not accepted: active work guard");
    });
    const waitForHealthy = vi.fn(async () => undefined);

    await expect(ensureWorkbenchBackendReady(baseInput({
      isBackendReachable,
      startLifecycle,
      waitForHealthy
    }))).rejects.toThrow("lifecycle start was not accepted");

    expect(waitForHealthy).not.toHaveBeenCalled();
  });

  it("times out into a failure when the backend never becomes healthy after start", async () => {
    const isBackendReachable = vi.fn(async () => false);
    const startLifecycle = vi.fn(async () => ({ accepted: true }));
    const waitForHealthy = vi.fn(async () => {
      throw new Error("workbench HTTP was not reachable at http://127.0.0.1:8000/");
    });

    await expect(ensureWorkbenchBackendReady(baseInput({
      isBackendReachable,
      startLifecycle,
      waitForHealthy,
      startWaitTimeoutMs: 1_500
    }))).rejects.toThrow("workbench HTTP was not reachable");

    expect(waitForHealthy.mock.calls[0][0].timeoutMs).toBeLessThanOrEqual(1_500);
  });

  it("fails the open action when a slow start exceeds the budget without pinning the caller", async () => {
    const isBackendReachable = vi.fn(async () => false);
    let startSettled = false;
    const startLifecycle = vi.fn(
      () => new Promise<void>((resolve) => {
        setTimeout(() => {
          startSettled = true;
          resolve();
        }, 250);
      })
    );
    const waitForHealthy = vi.fn(async () => undefined);

    await expect(ensureWorkbenchBackendReady(baseInput({
      isBackendReachable,
      startLifecycle,
      waitForHealthy,
      startWaitTimeoutMs: 20
    }))).rejects.toThrow("did not settle within 20ms");

    expect(waitForHealthy).not.toHaveBeenCalled();
    // The start itself is never cancelled; it settles in the background.
    await new Promise((resolve) => setTimeout(resolve, 300));
    expect(startSettled).toBe(true);
  });
});
