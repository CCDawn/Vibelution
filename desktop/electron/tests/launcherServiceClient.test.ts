import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";
import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";
import { stopPythonLauncherService } from "../src/process/launcherServiceClient.js";

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
    child.emit("close", 0);

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

  it("reaps leftover Python launcher via state-owned backend pid when no owned pid is known", async () => {
    const spawnCalls: Array<{ command: string; args: string[]; options: Record<string, unknown> }> = [];
    const child = fakeChildProcess();
    const stopPromise = stopPythonLauncherService({
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
          status: "stopped",
          reason: "",
          expectedBackendPid: 39368,
          launcherBackendPid: 39368,
          terminatedPids: [39368]
        }),
        "utf8"
      )
    );
    child.emit("close", 0);

    await expect(stopPromise).resolves.toEqual({
      schemaVersion: 1,
      status: "stopped",
      reason: "",
      expectedBackendPid: 39368,
      launcherBackendPid: 39368,
      terminatedPids: [39368]
    });
    expect(spawnCalls).toHaveLength(1);
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
      "--use-state-owned-backend-pid",
      "--no-browser"
    ]);
    expect(spawnCalls[0].args).not.toContain("--owned-backend-pid");
    expect(spawnCalls[0].options).toMatchObject({
      cwd: "C:/repo",
      windowsHide: true
    });
  });

  it("classifies malformed stop output through the shared invalid-payload path", async () => {
    const child = fakeChildProcess();
    const stopPromise = stopPythonLauncherService({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/operator/config.toml",
      spawnImpl: () => child
    });

    child.stdout.emit("data", Buffer.from("{not json", "utf8"));
    child.emit("close", 0);

    await expect(stopPromise).rejects.toBeInstanceOf(PythonJsonBridgeError);
    await expect(stopPromise).rejects.toMatchObject({ code: "invalid_payload" });
  });

  it("classifies a null stop result as an invalid payload", async () => {
    const child = fakeChildProcess();
    const stopPromise = stopPythonLauncherService({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/Python/python.exe",
      operatorConfigPath: "C:/operator/config.toml",
      spawnImpl: () => child
    });

    child.stdout.emit("data", Buffer.from("null", "utf8"));
    child.emit("close", 0);

    await expect(stopPromise).rejects.toMatchObject({ code: "invalid_payload" });
  });

  it("honors abort before spawning the stop bridge", async () => {
    const spawnImpl = vi.fn();
    const controller = new AbortController();
    controller.abort();

    await expect(
      stopPythonLauncherService({
        workspaceRoot: "C:/repo",
        pythonPath: "C:/Python/python.exe",
        operatorConfigPath: "C:/operator/config.toml",
        spawnImpl,
        signal: controller.signal
      })
    ).rejects.toMatchObject({ code: "aborted" });
    expect(spawnImpl).not.toHaveBeenCalled();
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
