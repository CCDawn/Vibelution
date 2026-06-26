import { describe, expect, it } from "vitest";
import { parseLauncherBootstrap } from "../src/process/launcherBootstrap.js";
import { initialManagedProcessState } from "../src/process/managedProcessTypes.js";
import {
  markProcessExited,
  markProcessFailed,
  markProcessRunning,
  markProcessStarting
} from "../src/process/launcherServiceProcess.js";

describe("python launcher service supervisor transitions", () => {
  it("records start and running pid for the single directly owned child", () => {
    const idle = initialManagedProcessState("python_launcher_service");
    const starting = markProcessStarting(idle, "2026-06-26T00:00:00.000Z");
    const running = markProcessRunning(starting, 1234);
    expect(running).toMatchObject({
      role: "python_launcher_service",
      status: "running",
      pid: 1234,
      startedAt: "2026-06-26T00:00:00.000Z"
    });
  });

  it("clears pid and records exit evidence", () => {
    const running = markProcessRunning(
      markProcessStarting(initialManagedProcessState("python_launcher_service"), "start"),
      2222
    );
    const exited = markProcessExited(running, 0, "", "end");
    expect(exited).toMatchObject({ status: "exited", pid: 0, exitCode: 0, exitedAt: "end" });
  });

  it("records failure reason", () => {
    const failed = markProcessFailed(initialManagedProcessState("python_launcher_service"), "spawn failed", "now");
    expect(failed).toMatchObject({ status: "failed", lastError: "spawn failed", exitedAt: "now" });
  });
});

describe("parseLauncherBootstrap", () => {
  it("accepts a ready bootstrap result with required capabilities", () => {
    const parsed = parseLauncherBootstrap(
      JSON.stringify({
        schemaVersion: 1,
        workspaceRoot: "C:/repo",
        operatorConfigPath: "C:/Users/17533/Documents/Vibelution/config/config.toml",
        workspaceId: "workspace-1",
        launcherInstanceId: "launcher-1",
        mode: "attached",
        launcherBackendPid: 1234,
        launcherUrl: "http://127.0.0.1:8765/launcher",
        workbenchUrl: "http://127.0.0.1:8000",
        ready: true,
        protocolVersion: 1,
        minDesktopProtocolVersion: 1,
        maxDesktopProtocolVersion: 1,
        capabilities: ["desktop_actions.claim", "desktop_sessions.heartbeat"]
      })
    );

    expect(parsed.mode).toBe("attached");
    expect(parsed.launcherBackendPid).toBe(1234);
  });

  it("rejects unready or capability-incomplete bootstrap output", () => {
    expect(() =>
      parseLauncherBootstrap(
        JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "C:/repo",
          operatorConfigPath: "",
          workspaceId: "",
          launcherInstanceId: "",
          mode: "started",
          launcherBackendPid: 0,
          launcherUrl: "",
          workbenchUrl: "",
          ready: false,
          protocolVersion: 1,
          minDesktopProtocolVersion: 1,
          maxDesktopProtocolVersion: 1,
          capabilities: []
        })
      )
    ).toThrow("invalid launcher bootstrap result");
  });
});
