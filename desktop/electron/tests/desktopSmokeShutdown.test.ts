import { describe, expect, it } from "vitest";
import { prepareDesktopSmokeShutdown } from "../src/smoke/desktopSmokeShutdown.js";
import type { LauncherBootstrapResult } from "../src/process/launcherBootstrap.js";

function bootstrap(overrides: Partial<LauncherBootstrapResult> = {}): LauncherBootstrapResult {
  return {
    schemaVersion: 1,
    workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
    operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
    workspaceId: "workspace",
    launcherInstanceId: "launcher",
    mode: "started",
    launcherBackendPid: 1234,
    launcherUrl: "http://127.0.0.1:8765/launcher",
    workbenchUrl: "http://127.0.0.1:8000/",
    ready: true,
    protocolVersion: 1,
    minDesktopProtocolVersion: 1,
    maxDesktopProtocolVersion: 1,
    capabilities: ["desktop_actions.claim"],
    ...overrides
  };
}

describe("prepareDesktopSmokeShutdown", () => {
  it("reuses the approved desktop shutdown path for started smoke bootstraps", async () => {
    const calls: string[] = [];

    const summary = await prepareDesktopSmokeShutdown({
      bootstrap: bootstrap(),
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
      }
    });

    expect(calls).toEqual([
      "close-session",
      "event:electron.launcher_service.stop_requested",
      "stop-python-launcher",
      "event:electron.launcher_service.exited",
      "approve-shutdown",
      "stop-action-loop"
    ]);
    expect(summary).toEqual({
      attempted: true,
      stopPythonLauncher: true,
      stopStatus: "stopped",
      stoppedPidCount: 1,
      stopError: ""
    });
  });
});
