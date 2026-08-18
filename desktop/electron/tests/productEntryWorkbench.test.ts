import { describe, expect, it, vi } from "vitest";

import { startOrFocusWorkbenchFromProductEntry } from "../src/windows/productEntryWorkbench.js";

describe("startOrFocusWorkbenchFromProductEntry", () => {
  it("focuses the live workbench when HTTP is already reachable", async () => {
    const openOrFocus = vi.fn(async () => undefined);
    const startLifecycle = vi.fn(async () => undefined);

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        url: "http://127.0.0.1:8002/",
        waitForHttp: async () => undefined,
        openOrFocus,
        startLifecycle
      })
    ).resolves.toBe("focused");

    expect(openOrFocus).toHaveBeenCalledWith("http://127.0.0.1:8002/");
    expect(startLifecycle).not.toHaveBeenCalled();
  });

  it("starts then opens the live URL when the probe cannot reach HTTP", async () => {
    const openOrFocus = vi.fn(async () => undefined);
    const startLifecycle = vi.fn(async () => undefined);
    const waitForHttp = vi.fn(async (opts: { url: string; timeoutMs: number }) => {
      if (opts.timeoutMs <= 1500) {
        throw new Error("workbench HTTP was not reachable");
      }
    });

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        url: "http://127.0.0.1:8000/",
        waitForHttp,
        openOrFocus,
        startLifecycle,
        resolveReadyUrl: async () => "http://127.0.0.1:8002/",
        readyTimeoutMs: 5_000
      })
    ).resolves.toBe("started");

    expect(startLifecycle).toHaveBeenCalledTimes(1);
    expect(openOrFocus).toHaveBeenCalledWith("http://127.0.0.1:8002/");
  });
});
