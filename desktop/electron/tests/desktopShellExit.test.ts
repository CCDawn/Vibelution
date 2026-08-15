import { describe, expect, it, vi } from "vitest";
import {
  DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS,
  executeApprovedDesktopShellShutdown,
  reapManagedRuntimeOnDesktopStart,
  withDesktopShellExitTimeout
} from "../src/shutdown/desktopShellExit.js";

describe("executeApprovedDesktopShellShutdown", () => {
  it("stops the owned Python Launcher before quitting the desktop shell", async () => {
    const calls: string[] = [];

    const result = await executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: true },
      closeDesktopSession: async () => {
        calls.push("close-session");
      },
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
      },
      stopManagedRuntime: async () => {
        calls.push("stop-managed-runtime");
      },
      stopPythonLauncher: async () => {
        calls.push("stop-python-launcher");
        return {
          schemaVersion: 1,
          status: "stopped",
          reason: "",
          expectedBackendPid: 1234,
          launcherBackendPid: 1234,
          terminatedPids: [1234]
        };
      },
      approveShutdown: () => {
        calls.push("approve-shutdown");
      },
      stopDesktopActionLoop: () => {
        calls.push("stop-action-loop");
      },
      quitApp: () => {
        calls.push("quit-app");
      }
    });

    expect(calls).toEqual([
      "close-session",
      "event:electron.runtime.stop_requested",
      "stop-managed-runtime",
      "event:electron.launcher_service.stop_requested",
      "stop-python-launcher",
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop",
      "quit-app"
    ]);
    expect(result).toEqual({
      stopManagedRuntime: true,
      managedRuntimeError: "",
      stopPythonLauncher: true,
      stopStatus: "stopped",
      stoppedPidCount: 1,
      stopError: ""
    });
  });

  it("stops managed project processes even when the Launcher was attached", async () => {
    const calls: string[] = [];

    const result = await executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: false },
      closeDesktopSession: async () => {
        calls.push("close-session");
      },
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
      },
      stopManagedRuntime: async () => {
        calls.push("stop-managed-runtime");
      },
      stopPythonLauncher: async () => {
        calls.push("stop-python-launcher");
        return {
          schemaVersion: 1,
          status: "stopped",
          reason: "",
          expectedBackendPid: 1234,
          launcherBackendPid: 1234,
          terminatedPids: [1234]
        };
      },
      approveShutdown: () => {
        calls.push("approve-shutdown");
      },
      stopDesktopActionLoop: () => {
        calls.push("stop-action-loop");
      },
      quitApp: () => {
        calls.push("quit-app");
      }
    });

    expect(calls).toEqual([
      "close-session",
      "event:electron.runtime.stop_requested",
      "stop-managed-runtime",
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop",
      "quit-app"
    ]);
    expect(result).toEqual({
      stopManagedRuntime: true,
      managedRuntimeError: "",
      stopPythonLauncher: false,
      stopStatus: "not_requested",
      stoppedPidCount: 0,
      stopError: ""
    });
  });

  it("fail-opens past a hung desktop session close so quit still runs", async () => {
    vi.useFakeTimers();
    const calls: string[] = [];
    const pending = executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: false },
      closeDesktopSession: async () => {
        await new Promise(() => undefined);
      },
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
      },
      stopManagedRuntime: async () => {
        calls.push("stop-managed-runtime");
      },
      stopPythonLauncher: async () => {
        throw new Error("should not stop");
      },
      approveShutdown: () => {
        calls.push("approve-shutdown");
      },
      stopDesktopActionLoop: () => {
        calls.push("stop-action-loop");
      },
      quitApp: () => {
        calls.push("quit-app");
      },
      stepTimeoutMs: 25
    });

    await vi.advanceTimersByTimeAsync(30);
    const result = await pending;
    expect(calls).toEqual([
      "event:electron.runtime.stop_requested",
      "stop-managed-runtime",
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop",
      "quit-app"
    ]);
    expect(result?.stopStatus).toBe("not_requested");
    vi.useRealTimers();
  });
});

describe("reapManagedRuntimeOnDesktopStart", () => {
  it("stops the previous managed process tree before the desktop shell continues starting", async () => {
    const calls: string[] = [];

    const result = await reapManagedRuntimeOnDesktopStart({
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
      },
      stopManagedRuntime: async () => {
        calls.push("stop-managed-runtime");
      }
    });

    expect(calls).toEqual([
      "event:electron.runtime.start_reap_requested",
      "stop-managed-runtime"
    ]);
    expect(result).toEqual({
      stopManagedRuntime: true,
      managedRuntimeError: ""
    });
  });

  it("fails open when the previous managed process tree cannot be stopped", async () => {
    const calls: string[] = [];

    const result = await reapManagedRuntimeOnDesktopStart({
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
      },
      stopManagedRuntime: async () => {
        calls.push("stop-managed-runtime");
        throw new Error("python missing");
      }
    });

    expect(calls).toEqual([
      "event:electron.runtime.start_reap_requested",
      "stop-managed-runtime",
      "event:electron.runtime.start_reap_failed"
    ]);
    expect(result).toEqual({
      stopManagedRuntime: true,
      managedRuntimeError: "python missing"
    });
  });
});

describe("withDesktopShellExitTimeout", () => {
  it("rejects when the operation exceeds the budget", async () => {
    vi.useFakeTimers();
    const pending = withDesktopShellExitTimeout(new Promise(() => undefined), 40, "demo");
    const assertion = expect(pending).rejects.toThrow(`demo timed out after 40ms`);
    await vi.advanceTimersByTimeAsync(40);
    await assertion;
    vi.useRealTimers();
  });

  it("exposes the default step timeout used by shell exit", () => {
    expect(DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS).toBeGreaterThan(0);
  });
});
