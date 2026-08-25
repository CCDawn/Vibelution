import { describe, expect, it, vi } from "vitest";

import { startOrFocusWorkbenchFromProductEntry } from "../src/windows/productEntryWorkbench.js";

describe("startOrFocusWorkbenchFromProductEntry", () => {
  it("always submits a lifecycle start instead of trusting a reachable old backend", async () => {
    const startLifecycle = vi.fn(async () => ({ accepted: true }));

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        startLifecycle
      })
    ).resolves.toBe("started");

    expect(startLifecycle).toHaveBeenCalledOnce();
  });

  it("surfaces a lifecycle rejection instead of focusing a stale workbench", async () => {
    const startLifecycle = vi.fn(async () => ({
      accepted: false,
      code: "active_work",
      message: "有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。"
    }));

    await expect(
      startOrFocusWorkbenchFromProductEntry({
        startLifecycle
      })
    ).rejects.toThrow("有进行中的任务");

    expect(startLifecycle).toHaveBeenCalledTimes(1);
  });
});
