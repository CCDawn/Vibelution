import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES,
  LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
  runPythonJsonBridge,
} from "../src/process/pythonJsonBridge.js";

function fakeSpawnWithOutput(output: string, exitCode = 0) {
  return vi.fn().mockImplementation(() => ({
    kill: vi.fn(),
    once: (event: string, listener: (...args: unknown[]) => void) => {
      if (event === "error") {
        return undefined;
      }
      queueMicrotask(() => listener(exitCode));
      return undefined;
    },
    stdout: {
      on: (_event: string, listener: (chunk: Buffer) => void) => {
        queueMicrotask(() => listener(Buffer.from(output, "utf8")));
        return undefined;
      },
    },
    stderr: { on: () => undefined },
  }));
}

describe("runPythonJsonBridge", () => {
  it("accepts launcher-api sized payloads that exceed the default 64KB cap", async () => {
    const payload = "x".repeat(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES + 1024);
    const spawnImpl = fakeSpawnWithOutput(payload);
    const raw = await runPythonJsonBridge({
      pythonPath: "python",
      args: ["--action", "launcher-api"],
      cwd: "C:/repo",
      spawnImpl,
      failureLabel: "launcher api bridge",
      maxBytes: LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
    });
    expect(raw).toHaveLength(payload.length);
    expect(LAUNCHER_API_JSON_BRIDGE_MAX_BYTES).toBeGreaterThan(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES);
  });

  it("rejects payloads over the default cap", async () => {
    const payload = "x".repeat(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES + 1024);
    const spawnImpl = fakeSpawnWithOutput(payload);
    await expect(
      runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "launcher api bridge",
      })
    ).rejects.toThrow(/output exceeded limit/);
  });
});
