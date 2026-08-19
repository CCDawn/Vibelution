import { describe, expect, it, vi } from "vitest";

import { waitForWorkbenchHttp, workbenchLoopbackUrl } from "../src/windows/workbenchHttpReady.js";

describe("workbenchLoopbackUrl", () => {
  it("uses the configured backend port when present", () => {
    expect(workbenchLoopbackUrl(8002)).toBe("http://127.0.0.1:8002/");
  });

  it("falls back to the packaged main checkout port", () => {
    expect(workbenchLoopbackUrl()).toBe("http://127.0.0.1:8002/");
  });
});

describe("waitForWorkbenchHttp", () => {
  it("resolves once the workbench origin answers", async () => {
    const fetchImpl = vi
      .fn()
      .mockRejectedValueOnce(new Error("fetch failed"))
      .mockResolvedValueOnce({ status: 200 });

    await waitForWorkbenchHttp({
      url: "http://127.0.0.1:8002/",
      timeoutMs: 100,
      pollIntervalMs: 0,
      fetchImpl
    });

    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("treats a non-server-error status as ready", async () => {
    const fetchImpl = vi.fn().mockResolvedValueOnce({ status: 307 });
    await waitForWorkbenchHttp({
      url: "http://127.0.0.1:8002/",
      timeoutMs: 100,
      pollIntervalMs: 0,
      fetchImpl
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("keeps polling through 5xx until the origin recovers", async () => {
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce({ status: 503 })
      .mockResolvedValueOnce({ status: 200 });
    await waitForWorkbenchHttp({
      url: "http://127.0.0.1:8002/",
      timeoutMs: 100,
      pollIntervalMs: 0,
      fetchImpl
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("times out while the backend is still down", async () => {
    let nowMs = 0;
    await expect(
      waitForWorkbenchHttp({
        url: "http://127.0.0.1:8002/",
        timeoutMs: 5,
        pollIntervalMs: 1,
        now: () => nowMs,
        delay: async (ms) => {
          nowMs += ms;
        },
        fetchImpl: async () => {
          throw new Error("ECONNREFUSED");
        }
      })
    ).rejects.toThrow(/not reachable/);
  });

  it("aborts a superseded HTTP observer during its polling delay", async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      const fetchImpl = vi.fn(async () => ({ status: 503 }));
      const pending = waitForWorkbenchHttp({
        url: "http://127.0.0.1:8002/",
        timeoutMs: 90_000,
        pollIntervalMs: 5_000,
        fetchImpl,
        signal: controller.signal
      });

      await vi.advanceTimersByTimeAsync(0);
      controller.abort(new Error("isolated observer superseded"));

      await expect(pending).rejects.toThrow("isolated observer superseded");
      expect(fetchImpl).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});
