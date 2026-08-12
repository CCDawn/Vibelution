import { describe, expect, it } from "vitest";
import {
  DesktopLifecycleCoordinator,
  DesktopSessionMutationQueue,
  desktopCloseReasonSupersedes,
  type DesktopCloseReason
} from "../src/lifecycle/desktopLifecycleCoordinator.js";

describe("DesktopLifecycleCoordinator", () => {
  it("shares one pending close operation across duplicate workbench close requests", async () => {
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
    const second = coordinator.request("workbench_window_close", runClose);

    expect(second).toBe(first);
    expect(calls).toBe(1);

    resolveClose?.("workbench_window_close");

    await expect(first).resolves.toBe("workbench_window_close");
    expect(coordinator.pendingReason()).toBeNull();
  });

  it("lets shell quit supersede an in-flight workbench close instead of hanging on it", async () => {
    let resolveClose: ((value: string) => void) | null = null;
    const coordinator = new DesktopLifecycleCoordinator();

    const closePromise = coordinator.request("workbench_window_close", async () => {
      await new Promise<string>((resolve) => {
        resolveClose = resolve;
      });
      return "close-finished";
    });

    expect(coordinator.pendingReason()).toBe("workbench_window_close");
    expect(desktopCloseReasonSupersedes("workbench_window_close", "desktop_shell_quit")).toBe(true);

    const quitPromise = coordinator.request("desktop_shell_quit", async () => "quit-finished");
    expect(quitPromise).not.toBe(closePromise);
    expect(coordinator.pendingReason()).toBe("desktop_shell_quit");

    await expect(quitPromise).resolves.toBe("quit-finished");
    expect(coordinator.pendingReason()).toBeNull();

    resolveClose?.("done");
    await expect(closePromise).resolves.toBe("close-finished");
  });

  it("still coalesces duplicate shell quit requests", async () => {
    let resolveQuit: ((value: string) => void) | null = null;
    let calls = 0;
    const coordinator = new DesktopLifecycleCoordinator();

    const first = coordinator.request("desktop_shell_quit", async () => {
      calls += 1;
      return await new Promise<string>((resolve) => {
        resolveQuit = resolve;
      });
    });
    const second = coordinator.request("desktop_shell_quit", async () => {
      calls += 1;
      return "second";
    });

    expect(second).toBe(first);
    expect(calls).toBe(1);
    resolveQuit?.("first");
    await expect(first).resolves.toBe("first");
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
