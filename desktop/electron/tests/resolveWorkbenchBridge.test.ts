import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { resolveWorkbenchUrlFromBridge } from "../src/process/resolveWorkbenchBridge.js";

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

describe("resolveWorkbenchUrlFromBridge", () => {
  it("spawns resolve-workbench with hidden stdio and returns the live URL", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({ schemaVersion: 1, workbenchUrl: "http://127.0.0.1:8002/" })
    );
    const url = await resolveWorkbenchUrlFromBridge({
      workspaceRoot: "C:/repo",
      pythonPath: "C:/repo/.venv/Scripts/python.exe",
      operatorConfigPath: "C:/Users/op/config.toml",
      spawnImpl,
    });
    expect(url).toBe("http://127.0.0.1:8002/");
    expect(spawnImpl).toHaveBeenCalledTimes(1);
    const [command, args, options] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(command).toBe("C:/repo/.venv/Scripts/python.exe");
    expect(args).toEqual([
      resolve("C:/repo", "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "resolve-workbench",
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
  });

  it("rejects a resolve-workbench payload without a workbenchUrl", async () => {
    const spawnImpl = fakeSpawnWithOutput(JSON.stringify({ schemaVersion: 1 }));
    await expect(
      resolveWorkbenchUrlFromBridge({
        workspaceRoot: "C:/repo",
        pythonPath: "C:/repo/.venv/Scripts/python.exe",
        operatorConfigPath: "C:/Users/op/config.toml",
        spawnImpl,
      })
    ).rejects.toThrow("resolve workbench bridge did not return a workbenchUrl");
  });
});
