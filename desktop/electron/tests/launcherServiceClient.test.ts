import { EventEmitter } from "node:events";
import { describe, expect, it } from "vitest";
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
