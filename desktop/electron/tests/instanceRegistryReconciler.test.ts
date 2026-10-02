import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import {
  createInstanceRegistryReconciler,
  observeBranchInstanceRuntimes,
  RECONCILE_ATTEMPT_COOLDOWN_MS,
  type ReconcilerDependencies
} from "../src/lifecycle/instanceRegistryReconciler.js";
import type { RegistryPayload } from "../src/lifecycle/instanceRegistryStore.js";

const tempDirs: string[] = [];

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop() as string, { recursive: true, force: true });
  }
});

function makeWorkspace(existingRoots: string[] = []): { root: string; missingRoot: string } {
  const dir = mkdtempSync(join(tmpdir(), "instance-registry-reconciler-"));
  tempDirs.push(dir);
  return {
    root: dir,
    missingRoot: existingRoots[0] || join(dir, "missing-worktree")
  };
}

function writeRegistry(path: string, payload: RegistryPayload): void {
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function readRegistryFile(path: string): RegistryPayload {
  return JSON.parse(readFileSync(path, "utf8")) as RegistryPayload;
}

/**
 * The real state-refresh payload ships branchInstances as the bridge source
 * envelope; the store only unwraps it after the reconciler hook runs. Tests
 * must feed this exact shape or the production defect this guards against
 * (items silently empty -> adopt never fires) cannot regress.
 */
function envelope(items: unknown[]): Record<string, unknown> {
  return {
    ok: true,
    value: { schemaVersion: 1, currentId: "main", items }
  };
}

function bareItems(items: unknown[]): Record<string, unknown> {
  return { schemaVersion: 1, currentId: "main", items };
}

function liveItem(input: {
  id: string;
  path: string;
  pid: number;
  port: number;
  controlPort?: number;
  branch?: string;
  windowOpen?: boolean;
}): Record<string, unknown> {
  return {
    id: input.id,
    kind: "worktree",
    path: input.path,
    branch: input.branch || "codex/branch",
    port: input.port,
    controlPort: input.controlPort || 0,
    runtime: {
      backend: { alive: true, healthy: true, listening: true, portConflict: false, pid: input.pid, port: input.port },
      window: { open: input.windowOpen === true, pid: 0 }
    }
  };
}

function deadItem(id: string, path: string, port: number): Record<string, unknown> {
  return {
    id,
    kind: "worktree",
    path,
    branch: "codex/branch",
    port,
    controlPort: 0,
    runtime: {
      backend: { alive: false, healthy: false, listening: false, portConflict: false, pid: 0, port },
      window: { open: false, pid: 0 }
    }
  };
}

type DepsOverrides = {
  pidAlive?: (pid: number) => boolean;
  pathExists?: (path: string) => boolean;
  captureIdentityCalls?: number[];
};

function buildDeps(overrides: DepsOverrides = {}): ReconcilerDependencies {
  return {
    readRegistry: (path) =>
      import("../src/lifecycle/instanceRegistryStore.js").then((store) => store.readRegistry(path)),
    adoptLiveInstance: (registryPath, input, options) =>
      import("../src/lifecycle/instanceRegistryStore.js").then((store) =>
        store.adoptLiveInstance(registryPath, input, options)
      ),
    closeConfirmedDeadInstance: (registryPath, input, options) =>
      import("../src/lifecycle/instanceRegistryStore.js").then((store) =>
        store.closeConfirmedDeadInstance(registryPath, input, options)
      ),
    sweepTerminatedRows: (registryPath, input, options) =>
      import("../src/lifecycle/instanceRegistryStore.js").then((store) =>
        store.sweepTerminatedRows(registryPath, input, options)
      ),
    captureIdentity: async (input) => {
      overrides.captureIdentityCalls?.push(input.pid);
      return { pid: input.pid, createTime: 133000000000000000, executable: "pythonw.exe" };
    },
    pidAlive: overrides.pidAlive || (() => true),
    pathExists: overrides.pathExists || (() => true)
  };
}

describe("instanceRegistryReconciler", () => {
  const t0 = Date.parse("2026-10-02T10:00:00Z");

  it("adopts an orphan backend onto a terminal row and is idempotent afterwards", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:orphan": {
          port: 8001,
          controlPort: 8767,
          projectRoot: workspace.root,
          branch: "codex/branch",
          status: "closed",
          generation: 4,
          portLeaseStatus: "reclaimable"
        }
      }
    });
    const identityCalls: number[] = [];
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({ captureIdentityCalls: identityCalls })
    });
    const branchInstances = envelope([
      liveItem({ id: "worktree:orphan", path: workspace.root, pid: 4242, port: 8001, controlPort: 8767 })
    ]);

    const first = await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0,
      pythonPath: "python"
    });
    expect(first.adopted).toEqual(["worktree:orphan"]);
    let entry = readRegistryFile(registryPath).instances["worktree:orphan"];
    expect(entry).toMatchObject({
      status: "steady",
      desiredState: "open",
      spawnPid: 4242,
      spawnCreateTime: 133000000000000000,
      spawnExecutable: "pythonw.exe",
      port: 8001,
      portLeaseStatus: "held",
      generation: 5
    });

    const second = await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0 + 1000,
      pythonPath: "python"
    });
    expect(second.adopted).toEqual([]);
    entry = readRegistryFile(registryPath).instances["worktree:orphan"];
    expect(entry.generation).toBe(5);
    expect(identityCalls).toEqual([4242]);
  });

  it("sweeps a dead key only after the observation grace", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:dead": {
          port: 8004,
          status: "closed",
          projectRoot: workspace.missingRoot,
          generation: 2
        }
      }
    });
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({
        pidAlive: () => false,
        pathExists: (path) => path === workspace.root
      })
    });

    const first = await reconciler.reconcile({ branchInstances: { items: [] }, registryPath, nowMs: t0 });
    expect(first.swept).toEqual([]);
    expect(readRegistryFile(registryPath).instances["worktree:dead"]).toBeDefined();

    const second = await reconciler.reconcile({
      branchInstances: { items: [] },
      registryPath,
      nowMs: t0 + 10_001
    });
    expect(second.swept).toEqual(["worktree:dead"]);
    expect(readRegistryFile(registryPath).instances["worktree:dead"]).toBeUndefined();
  });

  it("settles a steady row whose registered identity is confirmed dead", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:ghost": {
          port: 8002,
          status: "steady",
          desiredState: "open",
          spawnPid: 999,
          spawnCreateTime: 7,
          spawnExecutable: "pythonw.exe",
          portLeaseStatus: "held",
          projectRoot: workspace.root,
          generation: 6
        }
      }
    });
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({
        pidAlive: (pid) => pid > 0 && pid !== 999,
        pathExists: () => true
      })
    });
    const branchInstances = envelope([deadItem("worktree:ghost", workspace.root, 8002)]);

    const first = await reconciler.reconcile({ branchInstances, registryPath, nowMs: t0 });
    expect(first.closed).toEqual([]);
    expect(readRegistryFile(registryPath).instances["worktree:ghost"].status).toBe("steady");

    const second = await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0 + 10_001
    });
    expect(second.closed).toEqual(["worktree:ghost"]);
    expect(readRegistryFile(registryPath).instances["worktree:ghost"]).toMatchObject({
      status: "closed",
      desiredState: "closed",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });

  it("never kills an in-flight start that still has a live supervisor", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:launching": {
          port: 8005,
          status: "starting",
          desiredState: "open",
          spawnPid: 777,
          portLeaseStatus: "held",
          projectRoot: workspace.root,
          generation: 9,
          deadlineAt: new Date(t0 + 120_000).toISOString(),
          inFlightDeadlineAt: new Date(t0 + 120_000).toISOString(),
          ownerLease: { ownerId: "pid:1", expiresAt: new Date(t0 + 15_000).toISOString() }
        }
      }
    });
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({
        pidAlive: () => false,
        pathExists: () => true
      })
    });

    await reconciler.reconcile({ branchInstances: { items: [] }, registryPath, nowMs: t0 });
    await reconciler.reconcile({
      branchInstances: { items: [] },
      registryPath,
      nowMs: t0 + 10_001
    });
    expect(readRegistryFile(registryPath).instances["worktree:launching"]).toMatchObject({
      status: "starting",
      spawnPid: 777,
      portLeaseStatus: "held"
    });
  });

  it("rate-limits adopt attempts per instance with a cooldown", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:busy": {
          port: 8006,
          status: "steady",
          desiredState: "open",
          spawnPid: 111,
          portLeaseStatus: "held",
          projectRoot: workspace.root,
          generation: 3
        }
      }
    });
    const identityCalls: number[] = [];
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({
        captureIdentityCalls: identityCalls,
        pidAlive: () => true
      })
    });
    const branchInstances = envelope([
      liveItem({ id: "worktree:busy", path: workspace.root, pid: 4242, port: 8006 })
    ]);

    await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0,
      pythonPath: "python"
    });
    await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0 + 1000,
      pythonPath: "python"
    });
    expect(identityCalls).toEqual([4242]);
    expect(readRegistryFile(registryPath).instances["worktree:busy"].spawnPid).toBe(111);

    await reconciler.reconcile({
      branchInstances,
      registryPath,
      nowMs: t0 + RECONCILE_ATTEMPT_COOLDOWN_MS + 1,
      pythonPath: "python"
    });
    expect(identityCalls).toEqual([4242, 4242]);
  });

  it("serializes concurrent reconcile calls through the shared mutex", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:orphan": {
          port: 8001,
          projectRoot: workspace.root,
          status: "closed",
          generation: 1,
          portLeaseStatus: "reclaimable"
        }
      }
    });
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps()
    });
    // Bare items shape (post-unwrap store projection) must keep working too;
    // the other tests feed the raw bridge envelope.
    const branchInstances = bareItems([
      liveItem({ id: "worktree:orphan", path: workspace.root, pid: 4242, port: 8001 })
    ]);
    const [first, second] = await Promise.all([
      reconciler.reconcile({ branchInstances, registryPath, nowMs: t0 }),
      reconciler.reconcile({ branchInstances, registryPath, nowMs: t0 })
    ]);
    expect(second).toBe(first);
    expect(first.adopted).toEqual(["worktree:orphan"]);
  });

  it("protects rows whose scan shows an open window from the sweep", async () => {
    const workspace = makeWorkspace();
    const registryPath = join(workspace.root, "instances.json");
    writeRegistry(registryPath, {
      schemaVersion: 3,
      instances: {
        "worktree:window": {
          port: 8007,
          status: "closed",
          projectRoot: workspace.missingRoot,
          generation: 2
        }
      }
    });
    const reconciler = createInstanceRegistryReconciler({
      dependencies: buildDeps({
        pidAlive: () => false,
        pathExists: (path) => path === workspace.root
      })
    });
    await reconciler.reconcile({ branchInstances: envelope([]), registryPath, nowMs: t0 });
    await reconciler.reconcile({
      branchInstances: envelope([
        {
          id: "worktree:window",
          kind: "worktree",
          path: workspace.missingRoot,
          branch: "codex/branch",
          port: 8007,
          controlPort: 0,
          runtime: {
            backend: { alive: false, healthy: false, listening: false, portConflict: false, pid: 0, port: 8007 },
            window: { open: true, pid: 555 }
          }
        }
      ]),
      registryPath,
      nowMs: t0 + 10_001
    });
    expect(readRegistryFile(registryPath).instances["worktree:window"]).toBeDefined();
  });
});

describe("observeBranchInstanceRuntimes payload shapes", () => {
  const item = liveItem({ id: "worktree:shape", path: "C:/w", pid: 43128, port: 8010, controlPort: 8770 });

  it("yields identical liveBackends for the bridge envelope and the bare items array", () => {
    for (const shape of [envelope([item]), bareItems([item])]) {
      const observed = observeBranchInstanceRuntimes(shape);
      const live = observed.liveBackends.get("worktree:shape");
      expect(live).toBeDefined();
      expect(live).toMatchObject({ pid: 43128, port: 8010, controlPort: 8770, projectRoot: "C:/w" });
      expect(observed.openWindowIds.has("worktree:shape")).toBe(false);
    }
  });

  it("ignores failed source envelopes, the current item, and non-item garbage", () => {
    const failed = observeBranchInstanceRuntimes({ ok: false, errorType: "BridgeError", message: "source down" });
    expect(failed.liveBackends.size).toBe(0);
    expect(failed.openWindowIds.size).toBe(0);

    const currentItem = { ...liveItem({ id: "worktree:cur", path: "C:/w", pid: 1, port: 8000 }), current: true };
    const mixed = observeBranchInstanceRuntimes(envelope([currentItem, item, "garbage", null]));
    expect(mixed.liveBackends.size).toBe(1);
    expect(mixed.liveBackends.has("worktree:shape")).toBe(true);
  });

  it("registers open windows even when the backend is dead", () => {
    const observed = observeBranchInstanceRuntimes(envelope([
      {
        id: "worktree:win",
        path: "C:/w2",
        runtime: { backend: { alive: false, listening: false, pid: 0, port: 8009 }, window: { open: true, pid: 42 } }
      }
    ]));
    expect(observed.liveBackends.size).toBe(0);
    expect(observed.openWindowIds.has("worktree:win")).toBe(true);
  });
});
