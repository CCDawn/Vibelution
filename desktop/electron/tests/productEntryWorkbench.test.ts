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

  it("submits start without observing READY or opening a window when the probe cannot reach HTTP", async () => {
    const openOrFocus = vi.fn(async () => undefined);
    const startLifecycle = vi.fn(async () => undefined);
    const waitForHttp = vi.fn(async () => {
      throw new Error("workbench HTTP was not reachable");
    });

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        url: "http://127.0.0.1:8000/",
        waitForHttp,
        openOrFocus,
        startLifecycle
      })
    ).resolves.toBe("started");

    expect(startLifecycle).toHaveBeenCalledTimes(1);
    expect(waitForHttp).toHaveBeenCalledTimes(1);
    expect(openOrFocus).not.toHaveBeenCalled();
  });

  it("does not submit start when a reachable workbench fails to focus", async () => {
    const startLifecycle = vi.fn(async () => undefined);
    await expect(
      startOrFocusWorkbenchFromProductEntry({
        url: "http://127.0.0.1:8002/",
        waitForHttp: async () => undefined,
        openOrFocus: async () => {
          throw new Error("window creation failed");
        },
        startLifecycle
      })
    ).rejects.toThrow("window creation failed");
    expect(startLifecycle).not.toHaveBeenCalled();
  });
});
