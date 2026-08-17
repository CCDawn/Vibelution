import { resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { runBranchInstanceBridge, parseBranchInstanceBridgeResult } from "../src/process/branchInstanceBridge.js";

function fakeSpawnWithOutput(output: string, exitCode = 0): ReturnType<typeof vi.fn> {
  return vi.fn().mockImplementation((_command: string, _args: string[], _options: unknown) => ({
    kill: () => undefined,
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

describe("runBranchInstanceBridge", () => {
  it("spawns the Python branch-instance bridge with no-window options", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        accepted: true,
        operation: "start",
        instanceId: "worktree:task",
        port: 8002,
        message: "ok",
      })
    );
    const result = await runBranchInstanceBridge({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "start",
      instanceId: "worktree:task",
      spawnImpl,
    });
    expect(result.accepted).toBe(true);
    expect(result.instanceId).toBe("worktree:task");
    expect(result.port).toBe(8002);
    const [command, args, options] = spawnImpl.mock.calls[0] as [string, string[], Record<string, unknown>];
    expect(command).toBe("python");
    expect(args).toEqual([
      resolve("C:/repo", "scripts", "vibelution_desktop_entry.py"),
      "--action",
      "branch-instance",
      "--branch-instance-operation",
      "start",
      "--instance-id",
      "worktree:task",
      "--output",
      "json",
      "--workspace",
      "C:/repo",
      "--config",
      "",
      "--no-browser",
    ]);
    expect(options.windowsHide).toBe(true);
    expect(options.stdio).toEqual(["ignore", "pipe", "pipe"]);
  });

  it("passes generation and message for observe-error", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        accepted: true,
        operation: "observe-error",
        instanceId: "worktree:task",
        generation: 4,
      })
    );
    await runBranchInstanceBridge({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "observe-error",
      instanceId: "worktree:task",
      generation: 4,
      message: "HTTP timeout",
      spawnImpl,
    });
    const args = spawnImpl.mock.calls[0][1] as string[];
    expect(args).toContain("observe-error");
    expect(args).toContain("--branch-instance-generation");
    expect(args).toContain("4");
    expect(args).toContain("--branch-instance-message");
    expect(args).toContain("HTTP timeout");
  });

  it("surfaces failed operations with their code and message", async () => {
    const spawnImpl = fakeSpawnWithOutput(
      JSON.stringify({
        schemaVersion: 1,
        accepted: false,
        code: "branch_instance_operation_failed",
        operation: "start",
        instanceId: "worktree:task",
        message: "instance not operable",
      })
    );
    const result = await runBranchInstanceBridge({
      workspaceRoot: "C:/repo",
      pythonPath: "python",
      operatorConfigPath: "",
      operation: "start",
      instanceId: "worktree:task",
      spawnImpl,
    });
    expect(result.accepted).toBe(false);
    expect(result.code).toBe("branch_instance_operation_failed");
  });

  it("rejects non-zero bridge exits", async () => {
    const spawnImpl = fakeSpawnWithOutput("", 1);
    await expect(
      runBranchInstanceBridge({
        workspaceRoot: "C:/repo",
        pythonPath: "python",
        operatorConfigPath: "",
        operation: "stop",
        instanceId: "worktree:task",
        spawnImpl,
      })
    ).rejects.toThrow("branch instance bridge exited with code 1");
  });
});

describe("parseBranchInstanceBridgeResult", () => {
  it("validates the bridge schema", () => {
    expect(() => parseBranchInstanceBridgeResult("{}")).toThrow();
    expect(() =>
      parseBranchInstanceBridgeResult(
        JSON.stringify({ schemaVersion: 9, accepted: true, operation: "start" })
      )
    ).toThrow();
  });
});
