import { describe, expect, it } from "vitest";
import { executeApprovedDesktopShellShutdown } from "../src/shutdown/desktopShellExit.js";

describe("executeApprovedDesktopShellShutdown", () => {
  it("stops the owned Python Launcher before quitting the desktop shell", async () => {
    const calls: string[] = [];

    await executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: true },
      closeDesktopSession: async () => {
        calls.push("close-session");
      },
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
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
      "event:electron.launcher_service.stop_requested",
      "stop-python-launcher",
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop",
      "quit-app"
    ]);
  });

  it("detaches without stopping Python when the Launcher was attached", async () => {
    const calls: string[] = [];

    await executeApprovedDesktopShellShutdown({
      decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: false },
      closeDesktopSession: async () => {
        calls.push("close-session");
      },
      recordEvent: async (event) => {
        calls.push(`event:${event.eventCode}`);
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
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop",
      "quit-app"
    ]);
  });
});
