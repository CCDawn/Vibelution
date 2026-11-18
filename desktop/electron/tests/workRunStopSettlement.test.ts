import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { finalizeWorkRunsForStoppedBackend, listActiveWorkRuns } from "../src/process/activeWorkGuard.js";
import { executeMainLineWorkbench } from "../src/process/workbenchBackend.js";
import { runWorkbenchLifecycle } from "../src/process/workbenchLifecycle.js";
import { listDeferredRestartIntents, pruneTerminalDeferredRestartIntents } from "../src/lifecycle/deferredRestartIntents.js";

const tempRoots: string[] = [];

afterEach(() => {
  while (tempRoots.length > 0) {
    rmSync(tempRoots.pop() as string, { recursive: true, force: true });
  }
});

function makeWorkspaceRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "vibelution-work-run-stop-"));
  tempRoots.push(root);
  return root;
}

function writeRun(
  workspaceRoot: string,
  kind: string,
  runId: string,
  payload: Record<string, unknown>,
  activeRunId: string | null
): string {
  const kindDir = join(workspaceRoot, ".runtime", "runtime-manager", "work_runs", kind);
  mkdirSync(join(kindDir, "runs"), { recursive: true });
  if (activeRunId !== null) {
    writeFileSync(join(kindDir, "index.json"), JSON.stringify({ activeRunId }), "utf8");
  }
  const file = join(kindDir, "runs", `${runId}.json`);
  writeFileSync(file, JSON.stringify({
    runKind: kind,
    runId,
    status: "running",
    updatedAt: new Date().toISOString(),
    ...payload
  }), "utf8");
  return file;
}

/** The verified-retirement fake from the orphan stop tests: a registered
 * backend that acknowledges graceful shutdown and releases its port. */
function verifiedStopInput(workspaceRoot: string) {
  let alive = true;
  let listening = true;
  return {
    alive: () => alive,
    input: {
      workspaceRoot,
      pythonPath: join(workspaceRoot, ".venv", "Scripts", "python.exe"),
      operation: "force-stop" as const,
      command: { commandId: "cmd_settle_stop", type: "close", operation: "force-stop", noBrowser: true },
      readState: () => ({
        backendPid: 4242,
        backendCreateTime: 1,
        backendExecutable: "C:/Python/pythonw.exe",
        backendPort: 8000
      }),
      writeState: vi.fn((state: Record<string, unknown>) => state),
      connect: async () => listening,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4242, workspaceRoot })
      }),
      pidAlive: (pid: number) => pid === 4242 && alive,
      terminateProcessTree: vi.fn(async () => true),
      gracefulShutdown: vi.fn(async () => {
        alive = false;
        listening = false;
        return { requested: true, completed: true, status: 202, reason: "closed" };
      }),
      captureProcessIdentity: async ({ pid }: { pid: number }) => ({
        pid,
        createTime: 1,
        executable: "C:/Python/pythonw.exe"
      })
    }
  };
}

describe("work_runs settlement on a verified backend stop", () => {
  it("settles every blocking snapshot terminal so the guard releases the next restart", async () => {
    const root = makeWorkspaceRoot();
    // The indexed activeRunId is the forever-blocker (its stale grace is
    // intentionally disabled); the second run is a fresh unindexed "running"
    // snapshot that the six-hour grace would also keep blocking. The settled
    // run proves idempotence is read-based, not timestamp-based.
    const indexed = writeRun(root, "chat_turn", "current-run", {}, "current-run");
    const unindexed = writeRun(root, "chat_room_round", "round-1", {}, "");
    const settled = writeRun(root, "chat_turn", "already-settled",
      { status: "running", finishedAt: "2026-01-01T00:00:00.000Z" }, "");
    expect(listActiveWorkRuns(root).map((run) => run.runId).sort())
      .toEqual(["current-run", "round-1"]);

    const { input } = verifiedStopInput(root);
    await expect(executeMainLineWorkbench(input)).resolves.toMatchObject({ accepted: true, operation: "force-stop" });

    const indexedPayload = JSON.parse(readFileSync(indexed, "utf8")) as Record<string, unknown>;
    expect(indexedPayload).toMatchObject({
      status: "stopped",
      preStopStatus: "running",
      runtimeStatus: "orphan_reconciled",
      reconciliationSource: "electron_workbench_stop",
      runId: "current-run"
    });
    expect(String(indexedPayload.finishedAt || "").trim()).not.toBe("");
    // Settlement never invents success and never loses the original reading.
    expect(indexedPayload.status).not.toBe("completed");

    const unindexedPayload = JSON.parse(readFileSync(unindexed, "utf8")) as Record<string, unknown>;
    expect(unindexedPayload).toMatchObject({ status: "stopped", runtimeStatus: "orphan_reconciled" });

    // The end receipt already proved settlement: untouched by the reconcile.
    const settledPayload = JSON.parse(readFileSync(settled, "utf8")) as Record<string, unknown>;
    expect(settledPayload).not.toHaveProperty("reconciliationSource");
    expect(settledPayload.finishedAt).toBe("2026-01-01T00:00:00.000Z");

    // The indexed claim of the settled run is cleared; the guard now reads idle.
    const index = JSON.parse(readFileSync(
      join(root, ".runtime", "runtime-manager", "work_runs", "chat_turn", "index.json"), "utf8"
    )) as Record<string, unknown>;
    expect(index.activeRunId).toBe("");
    expect(listActiveWorkRuns(root)).toEqual([]);
  });

  it("is idempotent: a second settle pass rewrites nothing", () => {
    const root = makeWorkspaceRoot();
    writeRun(root, "chat_turn", "current-run", {}, "current-run");
    const first = finalizeWorkRunsForStoppedBackend({ workspaceRoot: root });
    expect(first.settledRunIds).toEqual(["current-run"]);
    expect(first.clearedIndexKinds).toEqual(["chat_turn"]);
    const file = join(root, ".runtime", "runtime-manager", "work_runs", "chat_turn", "runs", "current-run.json");
    const afterFirst = readFileSync(file, "utf8");
    const second = finalizeWorkRunsForStoppedBackend({ workspaceRoot: root });
    expect(second).toEqual({ settledRunIds: [], clearedIndexKinds: [] });
    expect(readFileSync(file, "utf8")).toBe(afterFirst);
  });

  it("keeps the index claim when the indexed run did not need settling", () => {
    const root = makeWorkspaceRoot();
    writeRun(root, "chat_turn", "idle-run", { status: "idle" }, "idle-run");
    const result = finalizeWorkRunsForStoppedBackend({ workspaceRoot: root });
    expect(result).toEqual({ settledRunIds: [], clearedIndexKinds: [] });
    const index = JSON.parse(readFileSync(
      join(root, ".runtime", "runtime-manager", "work_runs", "chat_turn", "index.json"), "utf8"
    )) as Record<string, unknown>;
    expect(index.activeRunId).toBe("idle-run");
  });

  it("routes the settlement through the stop-completion hook seam", async () => {
    const root = makeWorkspaceRoot();
    const { input } = verifiedStopInput(root);
    const settle = vi.fn();
    await expect(executeMainLineWorkbench({ ...input, settleActiveWorkOnStop: settle }))
      .resolves.toMatchObject({ accepted: true });
    expect(settle).toHaveBeenCalledExactlyOnceWith(root);
  });
});

/** A backend whose only registered handle is verifiably dead: the crash
 * scenario where the verified-stop settlement hook never ran and zombie
 * "running" snapshots would otherwise wedge stop and restart forever. */
function deadBackendLifecycleInput(workspaceRoot: string, operation: "stop" | "restart") {
  let spawned = false;
  const spawnImpl = vi.fn(() => {
    spawned = true;
    return { pid: 4243, exitCode: null as number | null, killed: false, unref: () => undefined, kill: () => true };
  });
  const written: Record<string, unknown>[] = [];
  const gracefulShutdown = vi.fn(async () => {
    spawned = true;
    return { requested: true, completed: true, status: 202, reason: "closed" };
  });
  const terminateProcessTree = vi.fn(async () => true);
  return {
    spawned: () => spawned,
    written,
    gracefulShutdown,
    terminateProcessTree,
    input: {
      workspaceRoot,
      pythonPath: join(workspaceRoot, ".venv", "Scripts", "python.exe"),
      operation,
      command: {
        commandId: operation === "stop" ? "cmd_dead_backend_stop" : "cmd_dead_backend_restart",
        type: operation,
        operation,
        noBrowser: true
      },
      spawnImpl,
      fileExists: (path: string) => path.endsWith("pythonw.exe") || path.endsWith("index.html"),
      readState: () => ({
        backendPid: 4242,
        backendCreateTime: 1,
        backendExecutable: "C:/Python/pythonw.exe",
        backendPort: 8000
      }),
      writeState: (state: Record<string, unknown>) => {
        written.push(state);
      },
      ensureFrontend: async () => undefined,
      connect: async () => spawned,
      fetchHealth: async () => ({
        status: 200,
        json: async () => ({ status: "ok", routesReady: true, pid: 4243, workspaceRoot })
      }),
      pidAlive: () => false,
      gracefulShutdown,
      terminateProcessTree,
      captureProcessIdentity: async ({ pid }: { pid: number }) => ({
        pid,
        createTime: 1,
        executable: "C:/Python/pythonw.exe"
      })
    }
  };
}

describe("work_runs escape when a blocked lifecycle command finds a dead backend", () => {
  it("stop releases a running snapshot once every registered backend handle is dead", async () => {
    const root = makeWorkspaceRoot();
    const snapshot = writeRun(root, "chat_turn", "zombie-turn", {}, "zombie-turn");
    expect(listActiveWorkRuns(root).map((run) => run.runId)).toEqual(["zombie-turn"]);

    const harness = deadBackendLifecycleInput(root, "stop");
    await expect(executeMainLineWorkbench(harness.input))
      .resolves.toMatchObject({ accepted: true, operation: "stop" });

    // The escape reused the orphan reconciliation: terminal receipt, stopped
    // verdict with the pre-stop reading kept for audit, index claim cleared.
    const payload = JSON.parse(readFileSync(snapshot, "utf8")) as Record<string, unknown>;
    expect(payload).toMatchObject({
      status: "stopped",
      preStopStatus: "running",
      runtimeStatus: "orphan_reconciled",
      reconciliationSource: "electron_workbench_stop"
    });
    expect(String(payload.finishedAt || "").trim()).not.toBe("");
    expect(listActiveWorkRuns(root)).toEqual([]);
  });

  it("restart executes instead of queueing behind a dead backend's running snapshot", async () => {
    const root = makeWorkspaceRoot();
    writeRun(root, "chat_turn", "zombie-turn", {}, "zombie-turn");

    const harness = deadBackendLifecycleInput(root, "restart");
    const result = await executeMainLineWorkbench(harness.input);
    expect(result.code).not.toBe("restart_queued");
    expect(result).toMatchObject({ accepted: true, operation: "restart" });
    // The guard released the restart, so the retirement + fresh spawn ran.
    expect(harness.spawned()).toBe(true);
    expect(listActiveWorkRuns(root)).toEqual([]);
  });

  it("keeps the guard's veto while a backend handle is alive, even with a running snapshot", async () => {
    const root = makeWorkspaceRoot();
    writeRun(root, "chat_turn", "live-turn", {}, "live-turn");
    const base = deadBackendLifecycleInput(root, "stop");
    const aliveBackend = {
      ...base.input,
      pidAlive: (pid: number) => pid === 4242
    };
    await expect(executeMainLineWorkbench(aliveBackend))
      .resolves.toMatchObject({ accepted: false, code: "active_work_blocked" });
    // The snapshot was never touched: no release, no settlement.
    expect(listActiveWorkRuns(root).map((run) => run.runId)).toEqual(["live-turn"]);

    const restart = deadBackendLifecycleInput(root, "restart");
    await expect(executeMainLineWorkbench({
      ...restart.input,
      pidAlive: (pid: number) => pid === 4242
    })).resolves.toMatchObject({ accepted: true, code: "restart_queued" });
    expect(restart.spawned()).toBe(false);
    expect(listActiveWorkRuns(root).map((run) => run.runId)).toEqual(["live-turn"]);
  });

  it("leaves a stop with no blocking snapshot and a dead backend unchanged", async () => {
    const root = makeWorkspaceRoot();
    const harness = deadBackendLifecycleInput(root, "stop");
    await expect(executeMainLineWorkbench(harness.input))
      .resolves.toMatchObject({ accepted: true, operation: "stop" });
    expect(listActiveWorkRuns(root)).toEqual([]);
    expect(harness.gracefulShutdown).not.toHaveBeenCalled();
    expect(harness.terminateProcessTree).not.toHaveBeenCalled();
  });
});

describe("restart intent garbage collection on accepted lifecycle commands", () => {
  it("drops failed and expired terminal intents behind an accepted stop", async () => {
    const root = makeWorkspaceRoot();
    const intentsDir = join(root, ".runtime", "runtime-manager", "restart-intents");
    mkdirSync(intentsDir, { recursive: true });
    const base = {
      target: "workbench_restart",
      reason: "blocked",
      requestedBy: "electron_main",
      sourceCommandId: "cmd-x",
      createdAt: "2026-01-01T00:00:00.000Z",
      updatedAt: "2026-01-01T00:00:00.000Z",
      payload: { action: "restart_workbench" }
    };
    writeFileSync(join(intentsDir, "failed.json"), JSON.stringify({
      intentId: "failed", status: "failed", ...base, createdAt: "2025-12-31T00:00:00.000Z"
    }));
    writeFileSync(join(intentsDir, "expired.json"), JSON.stringify({
      intentId: "expired", status: "expired", ...base, createdAt: "2026-01-01T00:00:00.000Z"
    }));
    writeFileSync(join(intentsDir, "pending.json"), JSON.stringify({ intentId: "pending", status: "pending", ...base }));
    writeFileSync(join(intentsDir, "claimed.json"), JSON.stringify({ intentId: "claimed", status: "claimed", ...base }));

    expect(pruneTerminalDeferredRestartIntents({
      runtimeManagerDir: join(root, ".runtime", "runtime-manager")
    })).toEqual(["failed", "expired"]);
    expect(existsSync(join(intentsDir, "failed.json"))).toBe(false);
    expect(existsSync(join(intentsDir, "expired.json"))).toBe(false);
    expect(existsSync(join(intentsDir, "pending.json"))).toBe(true);
    expect(existsSync(join(intentsDir, "claimed.json"))).toBe(true);
    expect(readdirSync(intentsDir).filter((name) => name.endsWith(".tmp"))).toEqual([]);
  });

  it("supersedes and prunes the queued intents behind an accepted runWorkbenchLifecycle stop", async () => {
    const root = makeWorkspaceRoot();
    const intentsDir = join(root, ".runtime", "runtime-manager", "restart-intents");
    mkdirSync(intentsDir, { recursive: true });
    const base = {
      target: "workbench_restart",
      reason: "有进行中的任务，无法重启 Vibelution。",
      requestedBy: "electron_main",
      sourceCommandId: "cmd-blocked-restart",
      updatedAt: "2026-01-01T00:00:00.000Z",
      payload: { action: "restart_workbench" }
    };
    writeFileSync(join(intentsDir, "pending.json"), JSON.stringify({
      intentId: "pending", status: "pending", ...base,
      createdAt: "2026-01-01T00:01:00.000Z"
    }));
    writeFileSync(join(intentsDir, "failed.json"), JSON.stringify({
      intentId: "failed", status: "failed", ...base,
      createdAt: "2026-01-01T00:00:00.000Z"
    }));
    writeFileSync(join(intentsDir, "claimed.json"), JSON.stringify({
      intentId: "claimed", status: "claimed", ...base,
      createdAt: "2026-01-01T00:02:00.000Z"
    }));

    const { input } = verifiedStopInput(root);
    await expect(runWorkbenchLifecycle({
      workspaceRoot: root,
      pythonPath: input.pythonPath,
      operatorConfigPath: join(root, "config.toml"),
      operation: "force-stop",
      readState: input.readState,
      writeState: input.writeState,
      // A settled workspace with no registered backend: the stop converges
      // without touching any process, and the accepted command still GCs.
      connect: async () => false,
      pidAlive: () => false,
      killPid: () => undefined,
      captureProcessIdentity: input.captureProcessIdentity,
      fileExists: () => true
    })).resolves.toMatchObject({ accepted: true, operation: "force-stop" });

    const remaining = listDeferredRestartIntents(join(root, ".runtime", "runtime-manager"));
    // The pending restart request was superseded by the accepted stop and its
    // file dropped together with the earlier failure: no accumulation across
    // repeated rejections. The in-flight claim keeps its file for evidence.
    expect(remaining.map((intent) => `${intent.intentId}:${intent.status}`)).toEqual(["claimed:claimed"]);
  });
});
