import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdmissionDeniedError } from "../src/lifecycle/instanceAdmissionControl.js";
import {
  admitLifecycleCommand,
  recordAdmissionOutcome,
  resetAdmissionCacheForTests
} from "../src/lifecycle/instanceAdmissionStore.js";
import {
  claimIsolatedStart,
  claimIsolatedStop,
  collectExtraUsedPorts,
  prepareIsolatedStart,
  resolveIsolatedClaimTarget,
  retireClaimedIsolatedRuntime,
  retireIsolatedRuntimeBeforeStart
} from "../src/lifecycle/isolatedInstanceRegistryHost.js";
import { claimStopIfGeneration, readRegistry } from "../src/lifecycle/instanceRegistryStore.js";

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
});
