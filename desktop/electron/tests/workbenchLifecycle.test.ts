import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";
import {
  runWorkbenchLifecycle,
  parseWorkbenchLifecycleResult,
  type WorkbenchLifecycleOperation,
} from "../src/process/workbenchLifecycle.js";

type SpawnChild = {
  kill(): void;
  once(event: string, listener: (...args: unknown[]) => void): unknown;
  stdout: { on(event: string, listener: (chunk: Buffer) => void): unknown };
  stderr: { on(event: string, listener: () => void): unknown };
};

function fakeSpawnWithOutput(output: string, exitCode = 0): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((_command: string, _args: string[], _options: unknown) => {
    const child: SpawnChild = {
      kill: () => undefined,
      once: (event, listener) => {
        if (event === "error") {
          return undefined;
        }
        queueMicrotask(() => listener(exitCode));
        return undefined;
      },
      stdout: {
        on: (_event, listener) => {
          queueMicrotask(() => listener(Buffer.from(output, "utf8")));
          return undefined;
        },
      },
      stderr: {
        on: () => undefined,
      },
    };
    return child;
  });
}

describe("runWorkbenchLifecycle", () => {
  it("spawns the Python lifecycle bridge with no-window process options", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, accepted: true, operation: "start", commandId: "cmd-1" })
    );
    const result = await runWorkbenchLifecycle({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operatorConfigPath: "C:/Users/op/config.toml",
      operation: "start",
      spawnImpl,
    });
    expect(result.accepted).toBe(true);
    expect(result.operation).toBe("start");
    expect(spawnImpl).toHaveBeenCalledTimes(1);
    const [command, args, options] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(command).toBe("C:/repo/.venv/Scripts/python.exe");
    expect(args).toEqual([
      resolve("C:/repo", "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "lifecycle",
      "--lifecycle-operation",
      "start",
      "--output",
      "json",
      "--workspace",
      "C:/repo",
      "--config",
      "C:/Users/op/config.toml",
      "--no-browser",
    ]);
    expect(options.cwd).toBe("C:/repo");
    expect(options.windowsHide).toBe(true);
    expect(options.stdio).toEqual(["ignore", "pipe", "pipe"]);
    expect((options.env as { PYTHONIOENCODING?: string; PYTHONUTF8?: string }).PYTHONIOENCODING).toBe("utf-8");
    expect((options.env as { PYTHONUTF8?: string }).PYTHONUTF8).toBe("1");
    expect(
      (options.env as { VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS?: string }).VIBELUTION_ELECTRON_MAIN_ORCHESTRATES_WINDOWS
    ).toBe("1");
  });

  it("passes shutdown through the lifecycle bridge", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, accepted: true, operation: "shutdown" })
    );
    const result = await runWorkbenchLifecycle({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "shutdown",
      spawnImpl,
    });
    expect(result.operation).toBe("shutdown");
    const [, args] = spawnImpl.mock.calls[0] as [string, string[]];
    expect(args).toContain("shutdown");
  });

  it("passes stop/restart/rebuild operations through the bridge", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, accepted: true, operation: "restart", commandId: "cmd-r" })
    );
    const result = await runWorkbenchLifecycle({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "restart",
      spawnImpl,
    });
    expect(result.operation).toBe("restart");
    const [, args] = spawnImpl.mock.calls[0] as [string, string[]];
    expect(args.includes("restart")).toBe(true);
  });

  it("surfaces active-work blocks as structured results", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        accepted: false,
        code: "active_work_blocked",
        operation: "stop",
        message: "有进行中的任务",
        activeWorkRuns: [],
      })
    );
    const result = await runWorkbenchLifecycle({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "stop",
      spawnImpl,
    });
    expect(result.accepted).toBe(false);
    expect(result.code).toBe("active_work_blocked");
  });

  it("rejects non-zero bridge exits", async () => {
    const spawnImpl = fakeSpawnWithOutput("", 1);
    await expect(
      runWorkbenchLifecycle({
        workspaceRoot: "C:/repo",
        pythonPath: "python",
        operatorConfigPath: "",
        operation: "start",
        spawnImpl,
      })
    ).rejects.toThrow("lifecycle bridge exited with code 1");
  });

  it("classifies malformed bridge output through the shared invalid-payload path", async () => {
    const spawnImpl = fakeSpawnWithOutput("{not json");
    const call = runWorkbenchLifecycle({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "start",
      spawnImpl,
    });
    await expect(call).rejects.toBeInstanceOf(PythonJsonBridgeError);
    await expect(call).rejects.toMatchObject({ code: "invalid_payload" });
  });

  it("rejects a result that is valid JSON but not the lifecycle schema", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, accepted: "yes", operation: "start" })
    );
    await expect(
      runWorkbenchLifecycle({
        workspaceRoot: "C:/repo",
        pythonPath: "python",
        operatorConfigPath: "",
        operation: "start",
        spawnImpl,
      })
    ).rejects.toMatchObject({ code: "invalid_payload" });
  });

  it("rejects with the bounded-helper abort classification before spawning", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, accepted: true, operation: "start" })
    );
    const controller = new AbortController();
    controller.abort();
    await expect(
      runWorkbenchLifecycle({
        workspaceRoot: "C:/repo",
        pythonPath: "python",
        operatorConfigPath: "",
        operation: "start",
        spawnImpl,
        signal: controller.signal,
      })
    ).rejects.toMatchObject({ code: "aborted" });
    expect(spawnImpl).not.toHaveBeenCalled();
  });
});

describe("parseWorkbenchLifecycleResult", () => {
  it("validates the bridge schema", () => {
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow();
    expect(() =>
      parseWorkbenchLifecycleResult(JSON.stringify({ schemaVersion: 2, accepted: true, operation: "start" }))
    ).toThrow();
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow(PythonJsonBridgeError);
  });

  it("returns the normalized lifecycle result", () => {
    const result = parseWorkbenchLifecycleResult(
      JSON.stringify({ schemaVersion: 1, accepted: true, operation: "start", commandId: "cmd-1", message: "ok" })
    );
    expect(result).toEqual({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
      commandId: "cmd-1",
      message: "ok",
    });
  });
});
