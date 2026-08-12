import { EventEmitter } from "node:events";
import { describe, expect, it } from "vitest";
import { bootstrapPythonLauncherService, stopPythonLauncherService } from "../src/process/launcherServiceClient.js";

describe("bootstrapPythonLauncherService", () => {
  it("requests attach-only handling for an already healthy managed Launcher", async () => {
    const spawnCalls: Array<{ command: string; args: string[]; options: Record<string, unknown> }> = [];
    const child = fakeChildProcess();
    const bootstrapPromise = bootstrapPythonLauncherService({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/operator/config.toml",
      spawnImpl: (command, args, options) => {
        spawnCalls.push({ command, args: [...args], options: options as Record<string, unknown> });
        return child;
      }
    });

    child.stdout.emit(
      "data",
      Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          workspaceRoot: "C:/repo",
          operatorConfigPath: "C:/operator/config.toml",
          workspaceId: "workspace-1",
          launcherInstanceId: "launcher-1",
          mode: "attached",
          launcherBackendPid: 1234,
          launcherUrl: "http://127.0.0.1:8765/launcher",
          workbenchUrl: "http://127.0.0.1:8002",
          ready: true,
          protocolVersion: 1,
          minDesktopProtocolVersion: 1,
          maxDesktopProtocolVersion: 1,
          capabilities: [
            "desktop_actions.claim",
            "desktop_sessions.heartbeat",
            "runtime_scene.electron_event",
            "workbench_close.transaction.v1"
          ]
        }),
        "utf8"
      )
    );
    child.emit("exit", 0);

    await expect(bootstrapPromise).resolves.toMatchObject({ mode: "attached", launcherBackendPid: 1234 });
    expect(spawnCalls).toHaveLength(1);
    expect(spawnCalls[0].args).toContain("--attach-healthy-launcher");
    expect(spawnCalls[0].options).toMatchObject({ cwd: "C:/repo", windowsHide: true });
  });
});

describe("stopPythonLauncherService", () => {
  it("routes owned shutdown through the Python desktop entry bridge", async () => {
    const spawnCalls: Array<{ command: string; args: string[]; options: Record<string, unknown> }> = [];
    const child = fakeChildProcess();
    const stopPromise = stopPythonLauncherService({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/operator/config.toml",
      launcherBackendPid: 1234,
      spawnImpl: (command, args, options) => {
        spawnCalls.push({ command, args: [...args], options: options as Record<string, unknown> });
        return child;
      }
    });

    child.stdout.emit(
      "data",
      Buffer.from(
        JSON.stringify({
          schemaVersion: 1,
          status: "stopped",
          reason: "",
          expectedBackendPid: 1234,
          launcherBackendPid: 1234,
          terminatedPids: [1234]
        }),
        "utf8"
      )
    );
    child.emit("exit", 0);

    await expect(stopPromise).resolves.toEqual({
      schemaVersion: 1,
      status: "stopped",
      reason: "",
      expectedBackendPid: 1234,
      launcherBackendPid: 1234,
      terminatedPids: [1234]
    });
    expect(spawnCalls).toHaveLength(1);
    expect(spawnCalls[0].command).toBe("C:/Python/python.exe");
    expect(spawnCalls[0].args).toEqual([
      "C:\\repo\\scripts\\vibelution_desktop_entry.py",
      "--action",
      "stop-launcher",
      "--output",
      "json",
      "--workspace",
      "C:/repo",
      "--config",
      "C:/operator/config.toml",
      "--owned-backend-pid",
      "1234",
      "--no-browser"
    ]);
    expect(spawnCalls[0].options).toMatchObject({
      cwd: "C:/repo",
      windowsHide: true
    });
  });
});

function fakeChildProcess(): EventEmitter & {
  stdout: EventEmitter;
  stderr: EventEmitter;
  kill: () => void;
} {
  const child = new EventEmitter() as EventEmitter & {
    stdout: EventEmitter;
    stderr: EventEmitter;
    kill: () => void;
  };
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.kill = () => undefined;
  return child;
}
