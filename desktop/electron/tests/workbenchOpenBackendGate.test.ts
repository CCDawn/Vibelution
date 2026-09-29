import { describe, expect, it, vi } from "vitest";
import { ensureWorkbenchBackendReady } from "../src/windows/workbenchOpenBackendGate.js";

const WORKSPACE_ROOT = "C:/tmp/fake-workspace";
const WORKBENCH_URL = "http://127.0.0.1:8000/";

function baseInput(overrides: Partial<Parameters<typeof ensureWorkbenchBackendReady>[0]> = {}) {
  return {
    workspaceRoot: WORKSPACE_ROOT,
    workbenchUrl: WORKBENCH_URL,
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

    expect(waitForHealthy).toHaveBeenCalledWith({ url: WORKBENCH_URL, timeoutMs: 1_500 });
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
