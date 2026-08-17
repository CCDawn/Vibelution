import { describe, expect, it, vi } from "vitest";

import {
  ISOLATED_INSTANCE_READY_WAIT_MS,
  superviseIsolatedInstanceStart,
} from "../src/process/isolatedInstanceSupervisor.js";

describe("superviseIsolatedInstanceStart", () => {
  it("uses a 180s isolated ready wait", () => {
    expect(ISOLATED_INSTANCE_READY_WAIT_MS).toBe(180_000);
  });

  it("opens the window and marks ready after HTTP succeeds", async () => {
    const waitForHttp = vi.fn().mockResolvedValue(undefined);
    const openWindow = vi.fn().mockResolvedValue(undefined);
    const markReady = vi.fn().mockResolvedValue(undefined);
    const markError = vi.fn();
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      generation: 4,
      timeoutMs: 50,
      waitForHttp,
      openWindow,
      markReady,
      markError,
    });
    expect(result).toBe("opened");
    expect(waitForHttp).toHaveBeenCalledWith("http://127.0.0.1:8003/", 50);
    expect(openWindow).toHaveBeenCalledTimes(1);
    expect(markReady).toHaveBeenCalledWith(4);
    expect(markError).not.toHaveBeenCalled();
  });

  it("writes observe-error for the same generation when HTTP times out", async () => {
    const markError = vi.fn().mockResolvedValue(undefined);
    const result = await superviseIsolatedInstanceStart({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8003/",
      generation: 7,
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
});
