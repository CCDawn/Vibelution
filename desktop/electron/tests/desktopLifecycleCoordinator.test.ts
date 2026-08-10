import { describe, expect, it } from "vitest";
import {
  DesktopLifecycleCoordinator,
  DesktopSessionMutationQueue,
  type DesktopCloseReason
} from "../src/lifecycle/desktopLifecycleCoordinator.js";

describe("DesktopLifecycleCoordinator", () => {
  it("shares one pending close operation across close, quit, and restart requests", async () => {
    let resolveClose: ((value: DesktopCloseReason) => void) | null = null;
    let calls = 0;
    const coordinator = new DesktopLifecycleCoordinator();
    const runClose = (reason: DesktopCloseReason) => {
      calls += 1;
      return new Promise<DesktopCloseReason>((resolve) => {
        resolveClose = resolve;
      });
    };

    const first = coordinator.request("workbench_window_close", runClose);
    const second = coordinator.request("desktop_shell_quit", runClose);
    const third = coordinator.request("desktop_shell_restart", runClose);

    expect(second).toBe(first);
    expect(third).toBe(first);
    expect(calls).toBe(1);

    resolveClose?.("workbench_window_close");

    await expect(first).resolves.toBe("workbench_window_close");
    expect(coordinator.pendingReason()).toBeNull();
  });

  it("records OS-session recovery without reusing a normal close reason", () => {
    const coordinator = new DesktopLifecycleCoordinator();

    expect(coordinator.recordSessionEnd()).toEqual({
      closeReason: "os_session_end",
      recoveryReason: "crash_recovery"
    });
  });

  it("serializes the closing mutation and drops later heartbeat or window writes", async () => {
    const queue = new DesktopSessionMutationQueue();
    const calls: string[] = [];
    let releaseHeartbeat: (() => void) | null = null;
    const heartbeat = queue.enqueue("heartbeat", () =>
      new Promise<string>((resolve) => {
        releaseHeartbeat = () => {
          calls.push("heartbeat");
          resolve("heartbeat");
        };
      })
    );
    const close = queue.enqueue("close", async () => {
      calls.push("close");
      return "closed";
    });

    await expect(queue.enqueue("window", async () => "late-window")).rejects.toThrow(
      "desktop session mutation dropped: window"
    );
    expect(queue.accepts("heartbeat")).toBe(false);
    expect(queue.enqueue("close", async () => "duplicate")).toBe(close);

    releaseHeartbeat?.();

    await expect(heartbeat).resolves.toBe("heartbeat");
    await expect(close).resolves.toBe("closed");
    expect(calls).toEqual(["heartbeat", "close"]);
  });
});
