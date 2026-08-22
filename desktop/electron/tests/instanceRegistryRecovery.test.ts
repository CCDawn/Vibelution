import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  completeStop,
  readRegistry,
  START_SUPERVISOR_LOST_MESSAGE,
  upsert,
  type RegistryPayload
} from "../src/lifecycle/instanceRegistryStore.js";
import {
  reconcileOrphanedInstanceRegistry
} from "../src/lifecycle/instanceRegistryRecovery.js";
import type { retireClaimedIsolatedRuntime } from "../src/lifecycle/isolatedInstanceRegistryHost.js";

const tempDirs: string[] = [];

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop() as string, { recursive: true, force: true });
  }
});
function createRegistry(instances: RegistryPayload["instances"]): string {
  const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-recovery-"));
  tempDirs.push(dir);
  const registryPath = join(dir, "instances.json");
  writeFileSync(registryPath, `${JSON.stringify({ schemaVersion: 3, instances }, null, 2)}\n`, "utf8");
  return registryPath;
}

function retirementStub() {
  return vi.fn(async (input: Parameters<typeof retireClaimedIsolatedRuntime>[0]) => {
    const completed = await completeStop(input.registryPath || "", {
      instanceId: input.instanceId,
      expectedGeneration: Number(input.entry.generation || 0)
    });
    if (completed.applied && input.successFailureMessage) {
      await upsert(
        input.registryPath || "",
        input.instanceId,
        {
          status: "failed",
          phase: "failed",
          desiredState: "open",
          failureMessage: input.successFailureMessage
        },
        Number(input.entry.generation || 0)
      );
    }
    return completed.applied
      ? { ok: true as const }
      : {
          ok: false as const,
          code: "backend_retire_incomplete" as const,
          generation: Number(input.entry.generation || 0),
          message: "retirement proof was not accepted"
        };
  });
}

describe("instance registry startup recovery", () => {
  it("retains a stale stop with a live registered handle when retirement is not proven", async () => {
    const registryPath = createRegistry({
      "worktree:live": {
        status: "stopping",
        phase: "stopping",
        desiredState: "closed",
        generation: 4,
        commandId: "stop-1",
        ownerPid: 101,
        spawnPid: 202,
        port: 8010,
        portLeaseStatus: "held",
        deadlineAt: "2026-08-20T11:59:00Z"
      }
    });
    const retire = vi.fn(async () => ({
      ok: false as const,
      code: "backend_retire_incomplete" as const,
      generation: 5,
      message: "backend identity was not verified"
    }));

    const result = await reconcileOrphanedInstanceRegistry({
      registryPath,
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      dependencies: {
        retireClaimed: retire,
        pidAlive: (pid) => pid === 202
      }
    });

    expect(result).toEqual({ reconciled: [], retained: ["worktree:live"] });
    expect(retire).toHaveBeenCalledTimes(1);
    const persisted = await readRegistry(registryPath);
    expect(persisted.instances["worktree:live"]).toMatchObject({
      status: "stopping",
      spawnPid: 202,
      portLeaseStatus: "held"
    });
  });

  it("closes a stale stop only after the retirement dependency proves it", async () => {
    const registryPath = createRegistry({
      "worktree:dead": {
        status: "stopping",
        phase: "stopping",
        desiredState: "closed",
        generation: 4,
        ownerPid: 101,
        spawnPid: 0,
        port: 8010,
        portLeaseStatus: "held",
        deadlineAt: "2026-08-20T11:59:00Z"
      }
    });
    const retire = retirementStub();

    const result = await reconcileOrphanedInstanceRegistry({
      registryPath,
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      dependencies: {
        retireClaimed: retire,
        pidAlive: () => false
      }
    });

    expect(result).toEqual({ reconciled: ["worktree:dead"], retained: [] });
    const persisted = await readRegistry(registryPath);
    expect(persisted.instances["worktree:dead"]).toMatchObject({
      status: "closed",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });

  it("reconciles an owner-less stale start on the next Electron startup", async () => {
    const registryPath = createRegistry({
      "worktree:start": {
        status: "starting",
        phase: "starting",
        desiredState: "open",
        generation: 4,
        commandId: "start-1",
        ownerPid: 101,
        spawnPid: 0,
        port: 8010,
        portLeaseStatus: "held",
        deadlineAt: "2026-08-20T11:59:00Z"
      }
    });
    const retire = retirementStub();

    const result = await reconcileOrphanedInstanceRegistry({
      registryPath,
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      dependencies: {
        retireClaimed: retire,
        pidAlive: () => false
      }
    });

    expect(result).toEqual({ reconciled: ["worktree:start"], retained: [] });
    expect(retire).toHaveBeenCalledWith(expect.objectContaining({
      desiredStateOnFailure: "open",
      successFailureMessage: START_SUPERVISOR_LOST_MESSAGE
    }));
    const persisted = await readRegistry(registryPath);
    expect(persisted.instances["worktree:start"]).toMatchObject({
      status: "failed",
      desiredState: "open",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });
});
