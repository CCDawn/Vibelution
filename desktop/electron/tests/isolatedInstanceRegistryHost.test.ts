import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdmissionDeniedError } from "../src/lifecycle/instanceAdmissionControl.js";
import * as backendState from "../src/process/workbenchBackend.js";
import {
  admitLifecycleCommand,
  recordAdmissionOutcome,
  resetAdmissionCacheForTests
} from "../src/lifecycle/instanceAdmissionStore.js";
import {
  claimIsolatedStart,
  claimIsolatedStop,
  collectExtraUsedPorts,
  inspectIsolatedStartReuse,
  prepareIsolatedStart,
  resolveIsolatedClaimTarget,
  retireClaimedIsolatedRuntime,
  retireIsolatedRuntimeBeforeStart
} from "../src/lifecycle/isolatedInstanceRegistryHost.js";
import { claimStopIfGeneration, readRegistry, upsert, type RegistryEntry } from "../src/lifecycle/instanceRegistryStore.js";
import {
  instanceIdForProject,
  normalizeInstanceKey,
  resolveDataHomeForProject
} from "../src/lifecycle/projectStoragePaths.js";

afterEach(() => {
  resetAdmissionCacheForTests();
});

const payload = {
  items: [
    { id: "main", path: "C:/repo", port: 8000, controlPort: 8765, current: true, alive: true },
    {
      id: "worktree:task",
      path: "C:/wt/task",
      branch: "task",
      port: 8003,
      controlPort: 8768,
      alive: false
    }
  ]
};

describe("isolatedInstanceRegistryHost", () => {
  const liveEntry: RegistryEntry = {
    projectRoot: "C:/wt/task", status: "steady", desiredState: "open", phase: "steady",
    portLeaseStatus: "held", generation: 7, commandId: "real-start-command",
    port: 8012, controlPort: 8777, spawnPid: 4242, spawnCreateTime: 123.45,
    spawnExecutable: "C:/python/pythonw.exe"
  };
  const liveIdentity = { pid: 4242, createTime: 123.45, executable: "C:/python/pythonw.exe" };
  function reuseDependencies(entry: RegistryEntry | undefined = liveEntry) {
    return {
      readRegistry: vi.fn(async () => ({ schemaVersion: 3, instances: entry ? { "worktree:task": entry } : {} })),
      readBackendIdentity: vi.fn(() => null as typeof liveIdentity | null),
      pidAlive: vi.fn(() => false),
      captureIdentity: vi.fn(async () => liveIdentity as typeof liveIdentity | null),
      connect: vi.fn(async () => true)
    };
  }
  function inspectReuse(dependencies: ReturnType<typeof reuseDependencies>, alive = true) {
    return inspectIsolatedStartReuse({
      target: { ...resolveIsolatedClaimTarget(payload, "worktree:task")!, alive },
      pythonPath: "python", registryPath: "test-only.json", dependencies
    });
  }

  it("starts again after stop despite stale cached alive truth", async () => {
    const dependencies = reuseDependencies({ ...liveEntry, status: "closed", desiredState: "closed", spawnPid: 0, spawnCreateTime: 0, spawnExecutable: "" });
    dependencies.connect.mockResolvedValue(false);
    expect(await inspectReuse(dependencies)).toEqual({ kind: "start" });
    expect(dependencies.captureIdentity).not.toHaveBeenCalled();
  });

  it("reuses authoritative command, generation and ports even when the cached alive flag is false", async () => {
    const dependencies = reuseDependencies();
    expect(await inspectReuse(dependencies, false)).toEqual({ kind: "reuse", entry: liveEntry });
    expect(dependencies.connect).toHaveBeenCalledWith(8012, "127.0.0.1");
    expect(dependencies.readRegistry).toHaveBeenCalledTimes(2);
  });

  it.each([null, { ...liveIdentity, createTime: 124 }, { ...liveIdentity, executable: "C:/unrelated.exe" }])(
    "does not reuse dead or recycled process identity %j", async (identity) => {
      const dependencies = reuseDependencies();
      dependencies.captureIdentity.mockResolvedValue(identity);
      dependencies.connect.mockResolvedValue(false);
      expect(await inspectReuse(dependencies)).toEqual({ kind: "start" });
    }
  );

  it("keeps a live unregistered runtime pending for existing reconciliation", async () => {
    const dependencies = reuseDependencies(undefined);
    // The default parameter models a live row; explicitly return a missing row.
    dependencies.readRegistry.mockResolvedValue({ schemaVersion: 3, instances: {} });
    dependencies.readBackendIdentity.mockReturnValue(liveIdentity);
    expect(await inspectReuse(dependencies)).toEqual({ kind: "pending", generation: 0 });
  });

  it("preserves an unregistered live backend recorded outside Runtime Manager", async () => {
    const dependencies = reuseDependencies();
    dependencies.readRegistry.mockResolvedValue({ schemaVersion: 3, instances: {} });
    dependencies.readBackendIdentity.mockReturnValue(liveIdentity);
    expect(await inspectReuse(dependencies)).toEqual({ kind: "pending", generation: 0 });
    expect(dependencies.captureIdentity).toHaveBeenCalledWith({
      pythonPath: "python", workspaceRoot: "C:/wt/task", pid: 4242
    });
  });

  it("does not mistake a live Runtime Manager daemon for a backend", async () => {
    const daemon = vi.spyOn(backendState, "readDaemonIdentity").mockReturnValue(liveIdentity);
    try {
      const dependencies = reuseDependencies({ ...liveEntry, status: "closed", spawnPid: 0, spawnCreateTime: 0, spawnExecutable: "" });
      dependencies.connect.mockResolvedValue(false);
      expect(await inspectReuse(dependencies)).toEqual({ kind: "start" });
      expect(daemon).not.toHaveBeenCalled();
    } finally { daemon.mockRestore(); }
  });

  it("does not authorize retirement when a stale registered identity has a live listener", async () => {
    const dependencies = reuseDependencies();
    dependencies.captureIdentity.mockResolvedValue({ ...liveIdentity, createTime: 999 });
    expect(await inspectReuse(dependencies)).toEqual({ kind: "pending", generation: 7 });
  });

  it.each([
    { status: "closed", desiredState: "closed" }, { portLeaseStatus: "reclaimable" },
    { commandId: "" }, { generation: 0 }, { projectRoot: "C:/another-task" }
  ])("does not acknowledge an unusable generation %j", async (fields) => {
    expect(await inspectReuse(reuseDependencies({ ...liveEntry, ...fields }))).toMatchObject({ kind: "pending" });
  });

  it("does not reuse a process without a listening backend", async () => {
    const dependencies = reuseDependencies();
    dependencies.connect.mockResolvedValue(false);
    expect(await inspectReuse(dependencies)).toEqual({ kind: "pending", generation: 7 });
  });

  it("does not acknowledge the old generation when stop wins during the process probe", async () => {
    const dependencies = reuseDependencies();
    dependencies.readRegistry.mockResolvedValueOnce({ schemaVersion: 3, instances: { "worktree:task": liveEntry } })
      .mockResolvedValueOnce({ schemaVersion: 3, instances: { "worktree:task": { ...liveEntry, generation: 8, status: "closed" } } });
    expect(await inspectReuse(dependencies)).toEqual({ kind: "pending", generation: 7 });
  });

  it("resolves claim targets and skips the selected row when collecting live ports", () => {
    const target = resolveIsolatedClaimTarget(payload, "worktree:task");
    expect(target).toEqual({
      instanceId: "worktree:task",
      projectRoot: "C:/wt/task",
      branch: "task",
      preferredBackend: 8003,
      preferredControl: 8768,
      extraUsed: [8000, 8765],
      alive: false
    });
    expect(collectExtraUsedPorts(payload, "worktree:task")).toEqual([8000, 8765]);
  });

  it("returns null when the instance path is missing", () => {
    expect(resolveIsolatedClaimTarget({ items: [{ id: "worktree:task" }] }, "worktree:task")).toBeNull();
  });

  it("persists canonical slot identity and data home in an isolated start claim", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-start-slot-fields-"));
    const projectRoot = join(dir, "checkout");
    const identityDir = join(projectRoot, ".vibelution");
    const registryPath = join(dir, "instances.json");
    const admissionStorePath = join(dir, "admission.json");
    await mkdir(identityDir, { recursive: true });
    await writeFile(
      join(identityDir, "project.json"),
      JSON.stringify({ schemaVersion: 1, projectId: "test-project" }),
      "utf8"
    );

    const expectedSlotFields = {
      slotKey: normalizeInstanceKey(projectRoot),
      slotId: instanceIdForProject(projectRoot),
      dataHome: resolveDataHomeForProject(projectRoot)
    };
    const claimed = await claimIsolatedStart({
      instanceId: "worktree:task",
      branchInstances: {
        items: [{
          id: "worktree:task",
          path: projectRoot,
          branch: "task",
          port: 8003,
          controlPort: 8768,
          alive: false
        }]
      },
      commandId: "start-with-slot-fields",
      registryPath,
      admissionStorePath,
      storeOptions: { portIsFree: async () => true }
    });

    expect(claimed.ok).toBe(true);
    if (!claimed.ok) {
      return;
    }
    expect(claimed.entry).toMatchObject(expectedSlotFields);
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject(expectedSlotFields);
  });

  it("rejects a fourth isolated start inside the burst window", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-admission-"));
    const admissionStorePath = join(dir, "instance-admission.json");
    const registryPath = join(dir, "instances.json");
    const nowMs = 1_787_227_200_000;
    for (let index = 0; index < 3; index += 1) {
      await admitLifecycleCommand({
        instanceId: "worktree:task",
        operation: "start",
        storePath: admissionStorePath,
        nowMs: nowMs + index
      });
    }
    await expect(
      claimIsolatedStart({
        instanceId: "worktree:task",
        branchInstances: payload,
        commandId: "cmd-4",
        nowMs: nowMs + 10,
        registryPath,
        admissionStorePath
      })
    ).rejects.toBeInstanceOf(AdmissionDeniedError);
  });

  it("rejects admission before touching a previously healthy runtime", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-admission-before-retire-"));
    const admissionStorePath = join(dir, "instance-admission.json");
    const registryPath = join(dir, "instances.json");
    const nowMs = 1_787_227_200_000;
    const original = {
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          port: 8003,
          controlPort: 8768,
          status: "steady",
          desiredState: "open",
          generation: 4,
          commandId: "healthy-command",
          spawnPid: 4242,
          portLeaseStatus: "held"
        }
      }
    };
    await writeFile(registryPath, JSON.stringify(original), "utf8");
    for (let index = 0; index < 3; index += 1) {
      await admitLifecycleCommand({
        instanceId: "worktree:task",
        operation: "start",
        storePath: admissionStorePath,
        nowMs: nowMs + index
      });
    }
    const reclaimBackend = vi.fn();

    await expect(prepareIsolatedStart({
      instanceId: "worktree:task",
      branchInstances: payload,
      operation: "restart",
      commandId: "denied-restart",
      nowMs: nowMs + 10,
      registryPath,
      admissionStorePath,
      retireDependencies: { reclaimBackend }
    })).rejects.toBeInstanceOf(AdmissionDeniedError);

    expect(reclaimBackend).not.toHaveBeenCalled();
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject(
      original.instances["worktree:task"]
    );
  });

  it("does not retire a healthy runtime during crash-loop cooldown", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-cooldown-before-retire-"));
    const admissionStorePath = join(dir, "instance-admission.json");
    const registryPath = join(dir, "instances.json");
    const nowMs = 1_787_227_200_000;
    await writeFile(registryPath, JSON.stringify({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          port: 8003,
          status: "steady",
          generation: 4,
          commandId: "healthy-command",
          spawnPid: 4242,
          portLeaseStatus: "held"
        }
      }
    }), "utf8");
    await recordAdmissionOutcome({
      instanceId: "worktree:task",
      outcome: "failure",
      storePath: admissionStorePath,
      nowMs
    });
    const reclaimBackend = vi.fn();

    await expect(prepareIsolatedStart({
      instanceId: "worktree:task",
      branchInstances: payload,
      operation: "restart",
      commandId: "cooldown-restart",
      nowMs: nowMs + 1_000,
      registryPath,
      admissionStorePath,
      retireDependencies: { reclaimBackend }
    })).rejects.toMatchObject({ code: "crash_loop_backoff" });
    expect(reclaimBackend).not.toHaveBeenCalled();
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject({
      status: "steady",
      generation: 4,
      commandId: "healthy-command",
      spawnPid: 4242
    });
  });

  it("persists the stop command id through the registry claim", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-stop-command-"));
    const registryPath = join(dir, "instances.json");
    await writeFile(registryPath, JSON.stringify({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          port: 8003,
          controlPort: 8768,
          status: "running",
          desiredState: "open",
          generation: 4,
          commandId: "start-cmd",
          spawnPid: 4242
        }
      }
    }), "utf8");

    const claimed = await claimIsolatedStop({
      instanceId: "worktree:task",
      branchInstances: payload,
      commandId: "stop-cmd",
      registryPath
    });
    expect(claimed.entry.commandId).toBe("stop-cmd");
    expect(claimed.entry.status).toBe("stopping");
  });

  it("reclaims the registered backend before completing a pre-start retirement", async () => {
    const events: string[] = [];
    const existing = {
      projectRoot: "C:/wt/task",
      host: "127.0.0.1",
      port: 8003,
      spawnPid: 4242,
      status: "steady",
      desiredState: "open",
      generation: 4
    };
    const claimed = { ...existing, status: "stopping", desiredState: "closed", generation: 5 };
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      dependencies: {
        readRegistry: async () => ({ schemaVersion: 3, instances: { "worktree:task": existing } }),
        claimStopIfGeneration: async () => {
          events.push("claim-stop");
          return { applied: true, entry: claimed };
        },
        reclaimBackend: async (input) => {
          events.push(`reclaim:${input.port}:${input.registeredPids?.join(",") || ""}`);
          return { reclaimed: true, reason: "reclaimed", verifiedPid: 4242 };
        },
        clearRuntimeState: () => {
          events.push("clear-runtime-state");
          return { cleared: true, removedCount: 2, failedCount: 0 };
        },
        completeStop: async () => {
          events.push("complete-stop");
          return { applied: true, entry: { ...claimed, status: "closed" } };
        },
        pidAlive: () => false
      }
    });

    expect(result).toEqual({ ok: true });
    expect(events).toEqual([
      "claim-stop",
      "reclaim:8003:4242",
      "clear-runtime-state",
      "complete-stop"
    ]);
  });

  it("reconciles dead isolated spawn and daemon handles before the kill path", async () => {
    const reclaimBackend = vi.fn(async (input) => {
      expect(input.registeredPids).toEqual([]);
      expect(input.extraPids).toEqual([]);
      return { reclaimed: true, reason: "port already released", verifiedPid: undefined };
    });
    const completeStop = vi.fn(async () => ({ applied: true, entry: { status: "closed" } }));
    const clearRuntimeState = vi.fn(() => ({ cleared: true, removedCount: 2, failedCount: 0 }));
    const result = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry: {
        projectRoot: "C:/wt/task",
        host: "127.0.0.1",
        port: 8003,
        spawnPid: 4242,
        spawnCreateTime: 101,
        spawnExecutable: "C:/Python/pythonw.exe",
        generation: 5,
        status: "stopping"
      },
      desiredStateOnFailure: "closed",
      dependencies: {
        readDaemonPid: () => 9191,
        readDaemonIdentity: () => ({
          pid: 9191,
          createTime: 202,
          executable: "C:/Python/pythonw.exe"
        }),
        connect: async () => false,
        pidAlive: () => false,
        reclaimBackend,
        clearRuntimeState,
        completeStop
      }
    });

    expect(result).toEqual({ ok: true });
    expect(reclaimBackend).toHaveBeenCalledOnce();
    expect(clearRuntimeState).toHaveBeenCalledOnce();
    expect(completeStop).toHaveBeenCalledOnce();
  });

  it("retains isolated handles when the port is listening or a pid is alive", async () => {
    const reclaimBackend = vi.fn(async () => ({ reclaimed: false, reason: "retirement remains unverified" }));
    const upsert = vi.fn(async () => ({ applied: true, entry: { status: "failed" } }));
    const entry = {
      projectRoot: "C:/wt/task",
      host: "127.0.0.1",
      port: 8003,
      spawnPid: 4242,
      spawnCreateTime: 101,
      spawnExecutable: "C:/Python/pythonw.exe",
      generation: 5,
      status: "stopping"
    };
    const daemonIdentity = {
      pid: 9191,
      createTime: 202,
      executable: "C:/Python/pythonw.exe"
    };
    const commonDependencies = {
      readDaemonPid: () => daemonIdentity.pid,
      readDaemonIdentity: () => daemonIdentity,
      reclaimBackend,
      upsert,
      completeStop: vi.fn(async () => ({ applied: true, entry: { status: "closed" } })),
      clearRuntimeState: vi.fn(() => ({ cleared: true, removedCount: 0, failedCount: 0 }))
    };

    const portListening = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry,
      desiredStateOnFailure: "closed",
      dependencies: {
        ...commonDependencies,
        connect: async () => true,
        pidAlive: () => false
      }
    });
    expect(portListening).toMatchObject({ ok: false, code: "backend_retire_incomplete" });
    expect(reclaimBackend.mock.calls[0]?.[0]).toMatchObject({
      registeredPids: [4242],
      extraPids: [9191]
    });

    reclaimBackend.mockClear();
    const pidAlive = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry,
      desiredStateOnFailure: "closed",
      dependencies: {
        ...commonDependencies,
        connect: async () => false,
        pidAlive: () => true
      }
    });
    expect(pidAlive).toMatchObject({ ok: false, code: "backend_retire_incomplete" });
    expect(reclaimBackend.mock.calls[0]?.[0]).toMatchObject({
      registeredPids: [4242],
      extraPids: [9191]
    });
  });

  it("does not force-retire an isolated backend after an HTTP active-work refusal", async () => {
    const reclaimBackend = vi.fn(async (input) => {
      if (input.forceRetireOnActiveWorkRefusal) {
        return { reclaimed: true, reason: "force retired", verifiedPid: undefined };
      }
      return {
        reclaimed: false,
        activeWorkBlocked: true,
        reason: "backend refused graceful shutdown because active work is running"
      };
    });
    const upsert = vi.fn(async () => ({ applied: true, entry: { status: "failed" } }));
    const completeStop = vi.fn(async () => ({ applied: true, entry: { status: "closed" } }));
    const clearRuntimeState = vi.fn(() => ({ cleared: true, removedCount: 1, failedCount: 0 }));
    const entry = {
      projectRoot: "C:/wt/task",
      host: "127.0.0.1",
      port: 8003,
      spawnPid: 4242,
      spawnCreateTime: 101,
      spawnExecutable: "C:/Python/pythonw.exe",
      generation: 5,
      status: "stopping"
    };
    const common = {
      readDaemonPid: () => 9191,
      readDaemonIdentity: () => ({
        pid: 9191,
        createTime: 202,
        executable: "C:/Python/pythonw.exe"
      }),
      reclaimBackend,
      upsert,
      completeStop,
      clearRuntimeState
    };

    const ordinary = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry,
      desiredStateOnFailure: "closed",
      dependencies: {
        ...common,
        connect: async () => true,
        pidAlive: () => true
      }
    });

    expect(ordinary).toMatchObject({ ok: false, code: "backend_retire_incomplete" });
    expect(reclaimBackend.mock.calls[0]?.[0]).toMatchObject({
      registeredPids: [4242],
      extraPids: [9191],
      forceRetireOnActiveWorkRefusal: false
    });
    expect(clearRuntimeState).not.toHaveBeenCalled();
    expect(completeStop).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(
      "C:/tmp/instances.json",
      "worktree:task",
      expect.objectContaining({ status: "failed", desiredState: "closed" }),
      5
    );

    const forced = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry,
      forceRetireOnActiveWorkRefusal: true,
      desiredStateOnFailure: "closed",
      dependencies: {
        ...common,
        connect: async () => false,
        pidAlive: () => false
      }
    });

    expect(forced).toEqual({ ok: true });
    expect(reclaimBackend.mock.calls[1]?.[0]).toMatchObject({
      forceRetireOnActiveWorkRefusal: true
    });
    expect(clearRuntimeState).toHaveBeenCalledOnce();
    expect(completeStop).toHaveBeenCalledOnce();
  });

  it("never passes a daemon pid with a mismatched identity to reclaim", async () => {
    const reclaimBackend = vi.fn(async (input) => {
      expect(input.registeredPids).toEqual([]);
      expect(input.extraPids).toEqual([]);
      expect(input.expectedIdentities).toEqual({
        "4242": {
          pid: 4242,
          createTime: 101,
          executable: "C:/Python/pythonw.exe"
        }
      });
      return { reclaimed: true, reason: "port already released", verifiedPid: undefined };
    });
    const result = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      entry: {
        projectRoot: "C:/wt/task",
        host: "127.0.0.1",
        port: 8003,
        spawnPid: 4242,
        spawnCreateTime: 101,
        spawnExecutable: "C:/Python/pythonw.exe",
        generation: 5,
        status: "stopping"
      },
      desiredStateOnFailure: "closed",
      dependencies: {
        readDaemonPid: () => 9191,
        readDaemonIdentity: () => ({
          pid: 9292,
          createTime: 202,
          executable: "C:/Python/pythonw.exe"
        }),
        connect: async () => false,
        pidAlive: () => false,
        reclaimBackend,
        clearRuntimeState: () => ({ cleared: true, removedCount: 0, failedCount: 0 }),
        completeStop: async () => ({ applied: true, entry: { status: "closed" } })
      }
    });

    expect(result).toEqual({ ok: true });
    expect(reclaimBackend).toHaveBeenCalledOnce();
  });

  it("keeps an alive registered pid from being confirmed closed before a new start", async () => {
    const upsert = vi.fn(async () => ({
      applied: true,
      entry: { status: "failed", generation: 5 }
    }));
    const completeStop = vi.fn(async () => ({ applied: true, entry: {} }));
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              projectRoot: "C:/wt/task",
              host: "127.0.0.1",
              port: 8003,
              spawnPid: 4242,
              status: "steady",
              desiredState: "open",
              generation: 4
            }
          }
        }),
        claimStopIfGeneration: async () => ({
          applied: true,
          entry: {
            projectRoot: "C:/wt/task",
            host: "127.0.0.1",
            port: 8003,
            spawnPid: 4242,
            status: "stopping",
            desiredState: "closed",
            generation: 5
          }
        }),
        reclaimBackend: async () => ({ reclaimed: true, reason: "port released", verifiedPid: 9911 }),
        clearRuntimeState: () => ({ cleared: true, removedCount: 0, failedCount: 0 }),
        completeStop,
        upsert,
        pidAlive: () => true
      }
    });

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.code).toBe("backend_retire_incomplete");
      expect(result.message).toContain("registered spawn pid 4242 is still alive");
    }
    expect(upsert).toHaveBeenCalledWith(
      "C:/tmp/instances.json",
      "worktree:task",
      expect.objectContaining({ status: "failed", phase: "failed" }),
      5
    );
    expect(completeStop).not.toHaveBeenCalled();
  });

  it("does not kill a newer runtime when the conditional stop claim loses its generation", async () => {
    const reclaimBackend = vi.fn();
    const claimStopIfGeneration = vi.fn(async () => ({
      applied: false,
      entry: {
        status: "starting",
        generation: 5,
        commandId: "newer-command",
        spawnPid: 5555,
        port: 8010
      }
    }));
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath: "C:/tmp/instances.json",
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              projectRoot: "C:/wt/task",
              status: "steady",
              generation: 4,
              commandId: "old-command",
              spawnPid: 4444,
              port: 8003
            }
          }
        }),
        claimStopIfGeneration,
        reclaimBackend
      }
    });

    expect(result).toMatchObject({ ok: false, code: "instance_busy", generation: 5 });
    expect(claimStopIfGeneration).toHaveBeenCalledWith(
      "C:/tmp/instances.json",
      expect.objectContaining({ expectedGeneration: 4, expectedCommandId: "old-command" })
    );
    expect(reclaimBackend).not.toHaveBeenCalled();
  });

  it("keeps an active start busy but retires an expired start owner", async () => {
    const base = {
      projectRoot: "C:/wt/task",
      host: "127.0.0.1",
      port: 8003,
      spawnPid: 4242,
      status: "starting",
      desiredState: "open",
      generation: 4,
      commandId: "start-command",
      deadlineAt: "2026-08-20T11:59:00Z"
    };
    const reclaimBackend = vi.fn(async () => ({ reclaimed: true, reason: "reclaimed", verifiedPid: 4242 }));
    const claimStopIfGeneration = vi.fn(async () => ({
      applied: true,
      entry: { ...base, status: "stopping", desiredState: "closed", generation: 5 }
    }));
    const active = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              ...base,
              ownerLease: { ownerId: "pid:1", expiresAt: "2026-08-20T12:01:00Z" }
            }
          }
        }),
        claimStopIfGeneration,
        reclaimBackend
      }
    });
    expect(active).toMatchObject({ ok: false, code: "instance_busy", generation: 4 });
    expect(claimStopIfGeneration).not.toHaveBeenCalled();

    const completed = vi.fn(async () => ({ applied: true, entry: { status: "closed", generation: 5 } }));
    const stale = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              ...base,
              ownerLease: { ownerId: "pid:1", expiresAt: "2026-08-20T11:58:00Z" }
            }
          }
        }),
        claimStopIfGeneration,
        reclaimBackend,
        completeStop: completed,
        clearRuntimeState: () => ({ cleared: true, removedCount: 2, failedCount: 0 }),
        pidAlive: () => false
      }
    });
    expect(stale).toEqual({ ok: true });
    expect(claimStopIfGeneration).toHaveBeenCalledOnce();
    expect(reclaimBackend).toHaveBeenCalledOnce();
    expect(reclaimBackend.mock.calls[0]?.[0].interruptActiveWork).toBeUndefined();
    expect(completed).toHaveBeenCalledOnce();
  });

  it("passes operator restart interruption through isolated pre-start retirement", async () => {
    const oldEntry = {
      projectRoot: "C:/wt/task",
      host: "127.0.0.1",
      port: 8003,
      status: "steady",
      desiredState: "open",
      generation: 4,
      commandId: "old-command"
    };
    const reclaimBackend = vi.fn(async () => ({ reclaimed: true, reason: "gracefully reclaimed", verifiedPid: 4242 }));
    const completed = vi.fn(async () => ({ applied: true, entry: { status: "closed", generation: 5 } }));
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      interruptActiveWork: true,
      dependencies: {
        readRegistry: async () => ({ schemaVersion: 3, instances: { "worktree:task": oldEntry } }),
        claimStopIfGeneration: async () => ({
          applied: true,
          entry: { ...oldEntry, status: "stopping", desiredState: "closed", generation: 5 }
        }),
        reclaimBackend,
        completeStop: completed,
        clearRuntimeState: () => ({ cleared: true, removedCount: 2, failedCount: 0 }),
        readDaemonPid: () => 0,
        readDaemonIdentity: () => null,
        connect: async () => false,
        pidAlive: () => false
      }
    });

    expect(result).toEqual({ ok: true });
    expect(reclaimBackend).toHaveBeenCalledWith(expect.objectContaining({ interruptActiveWork: true }));
    expect(completed).toHaveBeenCalledOnce();
  });

  it("settles a superseded pre-start stop claim to failed without killing its backend", async () => {
    const reclaimBackend = vi.fn();
    const upsert = vi.fn(async () => ({ applied: true, entry: { status: "failed", generation: 5 } }));
    const isCurrent = vi.fn()
      .mockReturnValueOnce(true)
      .mockReturnValueOnce(true)
      .mockReturnValue(false);
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      isCurrent,
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              projectRoot: "C:/wt/task",
              status: "steady",
              generation: 4,
              commandId: "old-command",
              spawnPid: 4242,
              port: 8003
            }
          }
        }),
        claimStopIfGeneration: async () => ({
          applied: true,
          entry: {
            projectRoot: "C:/wt/task",
            status: "stopping",
            generation: 5,
            commandId: "retire-command",
            spawnPid: 4242,
            port: 8003
          }
        }),
        reclaimBackend,
        upsert
      }
    });

    expect(result).toMatchObject({ ok: false, code: "backend_retire_incomplete", generation: 5 });
    expect(reclaimBackend).not.toHaveBeenCalled();
    expect(upsert).toHaveBeenCalledWith(
      expect.any(String),
      "worktree:task",
      expect.objectContaining({ status: "failed" }),
      5
    );
    expect(upsert.mock.calls[0]?.[2]).not.toHaveProperty("spawnPid");
  });

  it("closes a reclaimed backend but does not start again after supersession", async () => {
    let current = true;
    const completeStop = vi.fn(async () => ({ applied: true, entry: { status: "closed", generation: 5 } }));
    const result = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      isCurrent: () => current,
      dependencies: {
        readRegistry: async () => ({
          schemaVersion: 3,
          instances: {
            "worktree:task": {
              projectRoot: "C:/wt/task",
              status: "steady",
              generation: 4,
              commandId: "old-command",
              spawnPid: 4242,
              port: 8003
            }
          }
        }),
        claimStopIfGeneration: async () => ({
          applied: true,
          entry: {
            projectRoot: "C:/wt/task",
            status: "stopping",
            generation: 5,
            commandId: "retire-command",
            spawnPid: 4242,
            port: 8003
          }
        }),
        reclaimBackend: async () => {
          current = false;
          return { reclaimed: true, reason: "reclaimed", verifiedPid: 4242 };
        },
        pidAlive: () => false,
        clearRuntimeState: () => ({ cleared: true, removedCount: 2, failedCount: 0 }),
        completeStop
      }
    });

    expect(result).toMatchObject({
      ok: false,
      code: "lifecycle_intent_superseded",
      generation: 5
    });
    expect(completeStop).toHaveBeenCalledOnce();
  });

  it("preserves incomplete stop handles so a later restart can retire them", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-stop-retry-"));
    const registryPath = join(dir, "instances.json");
    const admissionStorePath = join(dir, "admission.json");
    await writeFile(registryPath, JSON.stringify({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          host: "127.0.0.1",
          port: 8003,
          controlPort: 8768,
          status: "steady",
          desiredState: "open",
          generation: 4,
          commandId: "start-command",
          spawnPid: 4242,
          portLeaseStatus: "held"
        }
      }
    }), "utf8");
    const claimed = await claimIsolatedStop({
      instanceId: "worktree:task",
      branchInstances: payload,
      commandId: "stop-command",
      registryPath
    });
    const incomplete = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      entry: claimed.entry,
      registryPath,
      desiredStateOnFailure: "closed",
      dependencies: {
        reclaimBackend: async () => ({ reclaimed: false, reason: "health identity unavailable" }),
        pidAlive: () => true
      }
    });
    expect(incomplete).toMatchObject({ ok: false, code: "backend_retire_incomplete" });
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject({
      status: "failed",
      desiredState: "closed",
      spawnPid: 4242,
      port: 8003,
      portLeaseStatus: "held"
    });

    const retired = await retireIsolatedRuntimeBeforeStart({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      registryPath,
      dependencies: {
        reclaimBackend: async () => ({ reclaimed: true, reason: "reclaimed", verifiedPid: 4242 }),
        pidAlive: () => false,
        clearRuntimeState: () => ({ cleared: true, removedCount: 2, failedCount: 0 })
      }
    });
    expect(retired).toEqual({ ok: true });
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject({
      status: "closed",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });

    const restarted = await claimIsolatedStart({
      instanceId: "worktree:task",
      branchInstances: payload,
      operation: "restart",
      commandId: "restart-command",
      registryPath,
      admissionStorePath,
      storeOptions: { portIsFree: async () => true }
    });
    expect(restarted.ok).toBe(true);
    if (restarted.ok) {
      expect(restarted.entry).toMatchObject({ status: "restarting", spawnPid: 0 });
    }
  });

  it("marks a cleaned health-wait failure retryable without stale spawn handles", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-health-failure-"));
    const registryPath = join(dir, "instances.json");
    const admissionStorePath = join(dir, "admission.json");
    await writeFile(registryPath, JSON.stringify({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          host: "127.0.0.1",
          port: 8003,
          controlPort: 8768,
          status: "starting",
          desiredState: "open",
          generation: 4,
          commandId: "start-command",
          spawnPid: 4242,
          portLeaseStatus: "held"
        }
      }
    }), "utf8");
    const claimed = await claimStopIfGeneration(registryPath, {
      instanceId: "worktree:task",
      expectedGeneration: 4,
      expectedCommandId: "start-command",
      commandId: "retire-health-failure"
    });
    expect(claimed.applied).toBe(true);
    const cleaned = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      entry: claimed.entry,
      registryPath,
      desiredStateOnFailure: "open",
      successFailureMessage: "workbench HTTP was not reachable",
      dependencies: {
        reclaimBackend: async () => ({ reclaimed: true, reason: "reclaimed", verifiedPid: 4242 }),
        pidAlive: () => false,
        clearRuntimeState: () => ({ cleared: true, removedCount: 2, failedCount: 0 })
      }
    });
    expect(cleaned).toEqual({ ok: true });
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject({
      status: "failed",
      desiredState: "open",
      failureMessage: "workbench HTTP was not reachable",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });

    const retried = await claimIsolatedStart({
      instanceId: "worktree:task",
      branchInstances: payload,
      commandId: "retry-command",
      registryPath,
      admissionStorePath,
      storeOptions: { portIsFree: async () => true }
    });
    expect(retried.ok).toBe(true);
  });

  it("keeps an identity-less dead spawn pending until its captured owner is CAS-cleared", async () => {
    const dir = await mkdtemp(join(tmpdir(), "vibe-isolated-owner-retirement-proof-"));
    const registryPath = join(dir, "instances.json");
    await writeFile(registryPath, JSON.stringify({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          projectRoot: "C:/wt/task",
          host: "127.0.0.1",
          port: 8003,
          controlPort: 8768,
          status: "starting",
          desiredState: "open",
          generation: 4,
          commandId: "start-command",
          spawnPid: 4242,
          portLeaseStatus: "held"
        }
      }
    }), "utf8");

    const firstClaim = await claimStopIfGeneration(registryPath, {
      instanceId: "worktree:task",
      expectedGeneration: 4,
      expectedCommandId: "start-command",
      commandId: "retire-without-identity"
    });
    expect(firstClaim.applied).toBe(true);
    let receivedPids: number[] = [];
    const retained = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      entry: firstClaim.entry,
      registryPath,
      desiredStateOnFailure: "open",
      dependencies: {
        readDaemonPid: () => 0,
        readDaemonIdentity: () => null,
        connect: async () => false,
        pidAlive: () => false,
        reclaimBackend: async (input) => {
          receivedPids = [...(input.registeredPids ?? [])];
          return receivedPids.includes(4242)
            ? { reclaimed: false, reason: "identity-less registered process remains pending" }
            : { reclaimed: true, reason: "port released after captured owner retirement" };
        }
      }
    });
    expect(receivedPids).toEqual([4242]);
    expect(retained.ok).toBe(false);
    const afterPending = await readRegistry(registryPath);
    expect(afterPending.instances["worktree:task"]).toMatchObject({
      status: "failed",
      spawnPid: 4242,
      generation: firstClaim.entry.generation
    });

    // This is the main-process compensation's proof boundary: only the same
    // registry generation can clear the handle after the captured Job owner
    // reports retirement and the port probe reports free.
    const cleared = await upsert(registryPath, "worktree:task", {
      spawnPid: 0,
      spawnCreateTime: 0,
      spawnExecutable: ""
    }, Number(firstClaim.entry.generation));
    expect(cleared.applied).toBe(true);
    const retryClaim = await claimStopIfGeneration(registryPath, {
      instanceId: "worktree:task",
      expectedGeneration: Number(firstClaim.entry.generation),
      expectedCommandId: "retire-without-identity",
      commandId: "settle-captured-retirement"
    });
    expect(retryClaim.applied).toBe(true);
    const settled = await retireClaimedIsolatedRuntime({
      instanceId: "worktree:task",
      workspaceRoot: "C:/wt/task",
      pythonPath: "python",
      entry: retryClaim.entry,
      registryPath,
      desiredStateOnFailure: "open",
      successFailureMessage: "isolated backend startup failed",
      dependencies: {
        readDaemonPid: () => 0,
        readDaemonIdentity: () => null,
        connect: async () => false,
        pidAlive: () => false,
        reclaimBackend: async (input) => {
          expect(input.registeredPids).toEqual([]);
          return { reclaimed: true, reason: "port released after captured owner retirement" };
        },
        clearRuntimeState: () => ({ cleared: true, removedCount: 0, failedCount: 0 })
      }
    });
    expect(settled).toEqual({ ok: true });
    expect((await readRegistry(registryPath)).instances["worktree:task"]).toMatchObject({
      status: "failed",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });
});
