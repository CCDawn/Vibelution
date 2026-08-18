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

  it("starts the current checkout when the probe cannot reach HTTP", async () => {
    const openOrFocus = vi.fn(async () => undefined);
    const startLifecycle = vi.fn(async () => undefined);

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        url: "http://127.0.0.1:8002/",
        waitForHttp: async () => {
          throw new Error("workbench HTTP was not reachable");
        },
        openOrFocus,
        startLifecycle
      })
    ).resolves.toBe("started");

    expect(openOrFocus).not.toHaveBeenCalled();
    expect(startLifecycle).toHaveBeenCalledTimes(1);
  });
});
