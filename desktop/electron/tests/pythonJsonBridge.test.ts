import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES,
  LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
  parsePythonJsonBridgePayload,
  PythonJsonBridgeError,
  runPythonJsonBridge,
} from "../src/process/pythonJsonBridge.js";

function fakeSpawnWithOutput(output: string, exitCode = 0) {
  const kill = vi.fn();
  const spawnImpl = vi.fn().mockImplementation(() => ({
    pid: 42,
    kill,
    once: (event: string, listener: (...args: unknown[]) => void) => {
      if (event !== "error") {
        queueMicrotask(() => listener(exitCode));
      }
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
  return { kill, spawnImpl };
}

function hangingSpawn(options: { exitOnKill?: boolean } = {}) {
  const listeners = new Map<string, (...args: unknown[]) => void>();
  const kill = vi.fn(() => {
    if (options.exitOnKill) {
      queueMicrotask(() => listeners.get("close")?.(null));
    }
    return true;
  });
  const child = {
    pid: 43,
    kill,
    once: (event: string, listener: (...args: unknown[]) => void) => {
      listeners.set(event, listener);
      return child;
    },
    stdout: { on: () => child.stdout },
    stderr: { on: () => child.stderr },
  };
  return { child, kill, spawnImpl: vi.fn(() => child) };
}

describe("runPythonJsonBridge", () => {
  it("accepts launcher-api sized payloads that exceed the default 64KB cap", async () => {
    const payload = "x".repeat(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES + 1024);
    const { spawnImpl } = fakeSpawnWithOutput(payload);
    const raw = await runPythonJsonBridge({
      pythonPath: "python",
      args: ["--action", "launcher-api"],
      cwd: "C:/repo",
      spawnImpl,
      failureLabel: "launcher api bridge",
      maxBytes: LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
      timeoutMs: 5_000,
      killPolicy: "child",
    });
    expect(raw).toHaveLength(payload.length);
    expect(LAUNCHER_API_JSON_BRIDGE_MAX_BYTES).toBeGreaterThan(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES);
  });

  it("kills the directly-owned child and rejects payloads over the default cap", async () => {
    const payload = "x".repeat(DEFAULT_PYTHON_JSON_BRIDGE_MAX_BYTES + 1024);
    const { kill, spawnImpl } = fakeSpawnWithOutput(payload);
    await expect(
      runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "launcher api bridge",
        timeoutMs: 5_000,
        killPolicy: "child",
      })
    ).rejects.toMatchObject({ code: "output_limit" });
    expect(kill).toHaveBeenCalledTimes(1);
  });

  it("bounds a child that never exits after timeout", async () => {
    vi.useFakeTimers();
    try {
      const { kill, spawnImpl } = hangingSpawn();
      const result = runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "status bridge",
        timeoutMs: 20,
        terminationGraceMs: 10,
        killPolicy: "child",
      });
      const rejection = expect(result).rejects.toMatchObject({ code: "timeout" });
      await vi.advanceTimersByTimeAsync(30);
      await rejection;
      expect(kill).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("marks a timed-out mutation as uncertain instead of retryable timeout", async () => {
    vi.useFakeTimers();
    try {
      const { spawnImpl } = hangingSpawn({ exitOnKill: true });
      const result = runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "mutation"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "mutation bridge",
        timeoutMs: 20,
        killPolicy: "child",
        mutation: true,
      });
      const rejection = expect(result).rejects.toMatchObject({
        code: "uncertain_mutation",
        causeCode: "timeout",
      });
      await vi.advanceTimersByTimeAsync(20);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });

  it("supports external abort and settles once after the child exits", async () => {
    const controller = new AbortController();
    const { kill, spawnImpl } = hangingSpawn({ exitOnKill: true });
    const result = runPythonJsonBridge({
      pythonPath: "python",
      args: ["--action", "status"],
      cwd: "C:/repo",
      spawnImpl,
      failureLabel: "status bridge",
      timeoutMs: 5_000,
      signal: controller.signal,
      killPolicy: "child",
    });
    controller.abort();
    await expect(result).rejects.toMatchObject({ code: "aborted" });
    expect(kill).toHaveBeenCalledTimes(1);
  });

  it("requires an explicit terminator for owned-tree policy", async () => {
    const { spawnImpl } = hangingSpawn();
    await expect(
      runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "status bridge",
        timeoutMs: 5_000,
        killPolicy: "owned-tree",
      })
    ).rejects.toThrow(/requires an explicit owned-tree terminator/);
    expect(spawnImpl).not.toHaveBeenCalled();
  });

  it("uses only the injected terminator for an owned tree", async () => {
    vi.useFakeTimers();
    try {
      const { child, kill, spawnImpl } = hangingSpawn();
      const terminateOwnedTree = vi.fn();
      const result = runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "status bridge",
        timeoutMs: 20,
        terminationGraceMs: 10,
        killPolicy: "owned-tree",
        terminateOwnedTree,
      });
      const rejection = expect(result).rejects.toMatchObject({ code: "timeout" });
      await vi.advanceTimersByTimeAsync(30);
      await rejection;
      expect(terminateOwnedTree).toHaveBeenCalledTimes(1);
      expect(terminateOwnedTree).toHaveBeenCalledWith(child);
      expect(kill).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps a no-kill policy bounded without terminating the child", async () => {
    vi.useFakeTimers();
    try {
      const { kill, spawnImpl } = hangingSpawn();
      const result = runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "status bridge",
        timeoutMs: 20,
        terminationGraceMs: 10,
        killPolicy: "none",
      });
      const rejection = expect(result).rejects.toMatchObject({ code: "timeout" });
      await vi.advanceTimersByTimeAsync(29);
      expect(kill).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      await rejection;
    } finally {
      vi.useRealTimers();
    }
  });

  it("classifies child process errors instead of leaking raw errors", async () => {
    const child = {
      pid: 44,
      kill: vi.fn(),
      once: (event: string, listener: (...args: unknown[]) => void) => {
        if (event === "error") {
          queueMicrotask(() => listener(new Error("spawn failed")));
        }
        return child;
      },
      stdout: { on: () => child.stdout },
      stderr: { on: () => child.stderr },
    };
    await expect(
      runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl: vi.fn(() => child),
        failureLabel: "status bridge",
        timeoutMs: 5_000,
        killPolicy: "child",
      })
    ).rejects.toMatchObject({ code: "nonzero_exit" });
  });

  it("classifies nonzero exit and malformed JSON", async () => {
    const { spawnImpl } = fakeSpawnWithOutput("", 7);
    await expect(
      runPythonJsonBridge({
        pythonPath: "python",
        args: ["--action", "status"],
        cwd: "C:/repo",
        spawnImpl,
        failureLabel: "status bridge",
        timeoutMs: 5_000,
        killPolicy: "child",
      })
    ).rejects.toMatchObject({ code: "nonzero_exit" });
    expect(() => parsePythonJsonBridgePayload("{", "status bridge")).toThrowError(PythonJsonBridgeError);
    try {
      parsePythonJsonBridgePayload("{", "status bridge");
    } catch (error: unknown) {
      expect(error).toMatchObject({ code: "invalid_payload" });
    }
  });
});
