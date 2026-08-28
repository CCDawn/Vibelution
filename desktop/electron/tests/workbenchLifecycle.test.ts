import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import { createMainLineCommandQueue } from "../src/lifecycle/mainLine/commandQueue.js";
import { mainLineCommandResultPath } from "../src/lifecycle/mainLine/commandEvidence.js";
import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";
import {
  MAIN_LINE_COMMAND_DEADLINE_MS,
  parseWorkbenchLifecycleResult,
  runWorkbenchLifecycle
} from "../src/process/workbenchLifecycle.js";

describe("parseWorkbenchLifecycleResult", () => {
  it("validates the bridge schema", () => {
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow();
    expect(() =>
      parseWorkbenchLifecycleResult(JSON.stringify({ schemaVersion: 2, accepted: true, operation: "start" }))
    ).toThrow();
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow(PythonJsonBridgeError);
  });

  it("accepts a schemaVersion 1 result", () => {
    expect(
      parseWorkbenchLifecycleResult(
        JSON.stringify({ schemaVersion: 1, accepted: true, operation: "start", commandId: "cmd-1" })
      )
    ).toEqual({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
      commandId: "cmd-1"
    });
  });
});

describe("runWorkbenchLifecycle command settlement evidence", () => {
  function makeWorkspace(): { root: string; runtimeManagerDir: string } {
    const root = mkdtempSync(join(tmpdir(), "vibelution-workbench-lifecycle-"));
    const runtimeManagerDir = join(root, ".runtime", "runtime-manager");
    mkdirSync(runtimeManagerDir, { recursive: true });
    // The daemon state fingerprint gates evidence writes.
    writeFileSync(join(runtimeManagerDir, "state.json"), "{}", "utf8");
    return { root, runtimeManagerDir };
  }

  function baseInput(root: string) {
    return {
      workspaceRoot: root,
      pythonPath: join(root, ".venv", "Scripts", "python.exe"),
      operatorConfigPath: join(root, "config.toml"),
      spawnImpl: () => {
        throw new Error("spawn must not run in this test");
      },
      readState: () => ({ backendPid: 0, backendPort: 8000 }),
      writeState: () => undefined,
      listActiveWork: () => [],
      connect: async () => false,
      pidAlive: () => false
    };
  }

  it("records durable evidence when the active-work guard rejects a stop", async () => {
    const { root, runtimeManagerDir } = makeWorkspace();
    try {
      const result = await runWorkbenchLifecycle({
        ...baseInput(root),
        operation: "stop",
        queue: createMainLineCommandQueue(),
        listActiveWork: () => [{ kind: "chat_turn", runId: "run-1", status: "running", sessionId: "s1" }]
      });
      expect(result).toMatchObject({ accepted: false, code: "active_work_blocked" });
      const resultPath = mainLineCommandResultPath(runtimeManagerDir, result.commandId || "");
      await vi.waitFor(() => expect(existsSync(resultPath)).toBe(true));
      const evidence = JSON.parse(readFileSync(resultPath, "utf8"));
      expect(evidence).toMatchObject({
        source: "electron_main",
        operation: "stop",
        accepted: false,
        code: "active_work_blocked"
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("aborts a command that exceeds its execution deadline and records the timeout", async () => {
    const { root, runtimeManagerDir } = makeWorkspace();
    try {
      const queue = createMainLineCommandQueue();
      const resultPromise = runWorkbenchLifecycle({
        ...baseInput(root),
        operation: "restart",
        queue,
        commandDeadlineMs: 1_000,
        ensureFrontend: ({ signal }) =>
          new Promise<void>((_resolve, reject) => {
            signal?.addEventListener("abort", () => reject(signal.reason), { once: true });
          })
      });
      await expect(resultPromise).rejects.toThrow(/execution deadline/);
      const submitted = queue.snapshot().pending;
      expect(submitted).toEqual([]);
      // The deadline settlement becomes durable evidence once the fire-and-forget
      // record resolves.
      await vi.waitFor(() => {
        const files = existsSync(join(runtimeManagerDir, "results"))
          ? readdirSync(join(runtimeManagerDir, "results"))
          : [];
        expect(files.length).toBe(1);
        const evidence = JSON.parse(readFileSync(join(runtimeManagerDir, "results", files[0] || ""), "utf8"));
        expect(evidence).toMatchObject({ operation: "restart", accepted: false, timedOut: true });
      });
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("keeps the legacy pre-spawn abort behaviour", async () => {
    const { root } = makeWorkspace();
    try {
      const controller = new AbortController();
      controller.abort();
      await expect(
        runWorkbenchLifecycle({
          ...baseInput(root),
          operation: "restart",
          queue: createMainLineCommandQueue(),
          signal: controller.signal
        })
      ).rejects.toThrow("workbench lifecycle was aborted before spawn");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("defaults the command deadline to 15 minutes", () => {
    expect(MAIN_LINE_COMMAND_DEADLINE_MS).toBe(900_000);
  });
});
