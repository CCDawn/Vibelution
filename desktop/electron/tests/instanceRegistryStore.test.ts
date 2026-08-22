import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  applyClaimStart,
  applyClaimStop,
  applyClaimStopIfGeneration,
  applyCompleteStop,
  applyObserve,
  applyRecordSpawnPid,
  applyReclaimStaleInFlightStart,
  applyRenewOwnerLease,
  applyUpsert,
  claimStart,
  claimStop,
  claimStopIfGeneration,
  ownerLeaseOf,
  reclaimStaleInFlightStops,
  recordSpawnPid,
  type RegistryPayload
} from "../src/lifecycle/instanceRegistryStore.js";

type CaseInput = {
  instanceId?: string;
  projectRoot?: string;
  branch?: string;
  operation?: "start" | "restart";
  commandId?: string;
  deadlineAt?: string;
  startedAt?: string;
  ownerPid?: number;
  ownerId?: string;
  nowMs?: number;
  preferredBackend?: number;
  preferredControl?: number;
  extraUsed?: number[];
  busyPorts?: number[];
  expectedGeneration?: number;
  message?: string;
  spawnPid?: number;
  fields?: Record<string, unknown>;
};

type CaseExpected = {
  ok?: boolean;
  applied?: boolean;
  code?: string;
  generation?: number;
  status?: string;
  phase?: string;
  desiredState?: string;
  port?: number;
  controlPort?: number;
  spawnPid?: number;
  windowPid?: number;
  portLeaseStatus?: string;
  commandId?: string;
  failureMessage?: string;
  ownerPid?: number;
  ownerId?: string;
  ownerLeaseExpiresAt?: string;
};

type FixtureCase = {
  id: string;
  op?: string;
  registry?: RegistryPayload;
  input?: CaseInput;
  expected?: CaseExpected;
  steps?: Array<{
    op: string;
    input?: CaseInput;
    expected?: CaseExpected;
  }>;
};

const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "lifecycle",
  "__fixtures__",
  "instanceRegistryCas.cases.json"
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as { cases: FixtureCase[] };
const tempDirs: string[] = [];

afterEach(() => {
  while (tempDirs.length > 0) {
    rmSync(tempDirs.pop() as string, { recursive: true, force: true });
  }
});

function cloneRegistry(raw: RegistryPayload | undefined): RegistryPayload {
  return structuredClone(raw ?? { schemaVersion: 2, instances: {} });
}

function portIsFree(input: CaseInput): (port: number) => boolean {
  const busy = new Set((input.busyPorts || []).map((port) => Math.trunc(port)));
  return (port) => !busy.has(Math.trunc(port));
}

function snapshot(entry: Record<string, unknown>): CaseExpected {
  const lease = ownerLeaseOf(entry);
  return {
    generation: Number(entry.generation || 0),
    status: String(entry.status || ""),
    phase: String(entry.phase || ""),
    desiredState: String(entry.desiredState || ""),
    port: Number(entry.port || 0),
    controlPort: Number(entry.controlPort || 0),
    spawnPid: Number(entry.spawnPid || 0),
    windowPid: Number(entry.windowPid || 0),
    portLeaseStatus: String(entry.portLeaseStatus || ""),
    commandId: String(entry.commandId || ""),
    failureMessage: String(entry.failureMessage || ""),
    ownerPid: Number(entry.ownerPid || 0),
    ownerId: lease?.ownerId || "",
    ownerLeaseExpiresAt: lease?.expiresAt || ""
  };
}

function assertExpected(actual: CaseExpected, expected: CaseExpected | undefined): void {
  if (!expected) {
    return;
  }
  for (const [key, value] of Object.entries(expected)) {
    expect(actual[key as keyof CaseExpected], key).toEqual(value);
  }
}

async function runOp(
  payload: RegistryPayload,
  op: string,
  input: CaseInput
): Promise<CaseExpected> {
  if (op === "claimStart") {
    const result = await applyClaimStart(payload, {
      instanceId: String(input.instanceId || ""),
      projectRoot: String(input.projectRoot || ""),
      branch: input.branch,
      operation: input.operation,
      commandId: String(input.commandId || ""),
      deadlineAt: String(input.deadlineAt || ""),
      startedAt: input.startedAt,
      ownerPid: Number(input.ownerPid || 0),
      ownerId: input.ownerId,
      nowMs: input.nowMs,
      preferredBackend: input.preferredBackend,
      preferredControl: input.preferredControl,
      extraUsed: input.extraUsed,
      portIsFree: portIsFree(input)
    });
    if (!result.ok) {
      return {
        ok: false,
        code: result.code,
        generation: result.generation,
        status: result.status
      };
    }
    return { ok: true, ...snapshot(result.entry) };
  }
  if (op === "claimStop") {
    const result = applyClaimStop(payload, {
      instanceId: String(input.instanceId || ""),
      projectRoot: input.projectRoot,
      commandId: input.commandId
    });
    return { ok: true, ...snapshot(result.entry) };
  }
  if (op === "observeReady" || op === "observeError") {
    const result = applyObserve(payload, {
      instanceId: String(input.instanceId || ""),
      operation: op === "observeReady" ? "observe-ready" : "observe-error",
      expectedGeneration: input.expectedGeneration,
      message: input.message
    });
    return { applied: result.applied, ...snapshot(result.entry) };
  }
  if (op === "recordSpawnPid") {
    const result = applyRecordSpawnPid(payload, {
      instanceId: String(input.instanceId || ""),
      spawnPid: Number(input.spawnPid || 0),
      expectedGeneration: Number(input.expectedGeneration || 0)
    });
    return { applied: result.applied, ...snapshot(result.entry) };
  }
  if (op === "reclaimStale") {
    const result = applyReclaimStaleInFlightStart(payload, {
      instanceId: String(input.instanceId || ""),
      nowMs: input.nowMs,
      expectedGeneration: input.expectedGeneration
    });
    return { applied: result.applied, ...snapshot(result.entry) };
  }
  if (op === "renewOwnerLease") {
    const result = applyRenewOwnerLease(payload, {
      instanceId: String(input.instanceId || ""),
      ownerId: String(input.ownerId || ""),
      expectedGeneration: input.expectedGeneration,
      nowMs: input.nowMs
    });
    return { applied: result.applied, ...snapshot(result.entry) };
  }
  if (op === "upsert") {
    const result = applyUpsert(
      payload,
      String(input.instanceId || ""),
      input.fields || {},
      input.expectedGeneration
    );
    return { applied: result.applied, ...snapshot(result.entry) };
  }
  throw new Error(`unknown op ${op}`);
}

describe("instanceRegistryStore shared fixture", () => {
  it("locks dual-language CAS cases", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(15);
    const ids = fixture.cases.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each(fixture.cases)("$id", async (item) => {
    const payload = cloneRegistry(item.registry);
    const steps = item.steps?.length ? item.steps : [{ op: String(item.op), input: item.input, expected: item.expected }];
    let last: CaseExpected = {};
    for (const step of steps) {
      last = await runOp(payload, step.op, step.input || {});
      assertExpected(last, step.expected);
    }
    assertExpected(last, item.expected);
  });

  it("discards a lock-wrapped spawnPid write after claimStop", async () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-cas-"));
    tempDirs.push(dir);
    const registryPath = join(dir, "instances.json");
    const payload = cloneRegistry({
      schemaVersion: 2,
      instances: {
        "worktree:task": {
          status: "starting",
          generation: 1,
          spawnPid: 4242
        }
      }
    });
    const { writeFileSync } = await import("node:fs");
    writeFileSync(registryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
    const claimed = await claimStop(registryPath, { instanceId: "worktree:task" });
    expect(claimed.entry.generation).toBe(2);
    expect(claimed.entry.portLeaseStatus).toBe("held");
    const stale = await recordSpawnPid(registryPath, {
      instanceId: "worktree:task",
      spawnPid: 9999,
      expectedGeneration: 1
    });
    expect(stale.applied).toBe(false);
    expect(stale.entry.spawnPid).toBe(4242);
    expect(stale.entry.status).toBe("stopping");
  });

  it("does not let a stale read claim stop over a newer generation", async () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-stop-cas-"));
    tempDirs.push(dir);
    const registryPath = join(dir, "instances.json");
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "steady",
          desiredState: "open",
          generation: 4,
          commandId: "old-command",
          spawnPid: 4242,
          port: 8003
        }
      }
    });
    const { writeFileSync } = await import("node:fs");
    writeFileSync(registryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

    const newer = await claimStop(registryPath, {
      instanceId: "worktree:task",
      commandId: "newer-command"
    });
    expect(newer.entry.generation).toBe(5);

    const stale = await claimStopIfGeneration(registryPath, {
      instanceId: "worktree:task",
      expectedGeneration: 4,
      expectedCommandId: "old-command",
      commandId: "stale-retire"
    });
    expect(stale.applied).toBe(false);
    expect(stale.entry).toMatchObject({
      generation: 5,
      commandId: "newer-command",
      status: "stopping",
      spawnPid: 4242
    });
  });

  it("checks command id in the same conditional stop claim", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "steady",
          generation: 7,
          commandId: "current-command",
          spawnPid: 7007
        }
      }
    });
    const result = applyClaimStopIfGeneration(payload, {
      instanceId: "worktree:task",
      expectedGeneration: 7,
      expectedCommandId: "stale-command",
      commandId: "retire-command"
    });
    expect(result.applied).toBe(false);
    expect(result.entry).toMatchObject({
      generation: 7,
      commandId: "current-command",
      status: "steady",
      spawnPid: 7007
    });
  });

  it("settles a successful stop to closed and releases its port lease", () => {
    const payload = cloneRegistry({
      schemaVersion: 2,
      instances: {
        "worktree:task": {
          status: "starting",
          phase: "starting",
          desiredState: "open",
          generation: 4,
          spawnPid: 4242,
          windowPid: 4343,
          port: 8010,
          controlPort: 8770,
          portLeaseStatus: "held"
        }
      }
    });
    const claimed = applyClaimStop(payload, {
      instanceId: "worktree:task",
      commandId: "stop-cmd-1"
    });
    expect(claimed.entry.commandId).toBe("stop-cmd-1");
    const completed = applyCompleteStop(payload, {
      instanceId: "worktree:task",
      expectedGeneration: claimed.entry.generation
    });
    expect(completed.applied).toBe(true);
    expect(completed.entry).toMatchObject({
      status: "closed",
      phase: "steady",
      desiredState: "closed",
      spawnPid: 0,
      windowPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });

  it("does not complete a stale stop over a newer generation", () => {
    const payload = cloneRegistry({
      schemaVersion: 2,
      instances: {
        "worktree:task": { status: "stopping", desiredState: "closed", generation: 8 }
      }
    });
    const result = applyCompleteStop(payload, {
      instanceId: "worktree:task",
      expectedGeneration: 7
    });
    expect(result.applied).toBe(false);
    expect(result.entry.status).toBe("stopping");
  });

  it("does not let the pure start reclaimer wash a stale stopping row", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "stopping",
          phase: "stopping",
          desiredState: "closed",
          generation: 9,
          spawnPid: 4242,
          windowPid: 4343,
          port: 8010,
          controlPort: 8770,
          portLeaseStatus: "held",
          deadlineAt: "2026-08-20T11:59:00Z"
        }
      }
    });

    const result = applyReclaimStaleInFlightStart(payload, {
      instanceId: "worktree:task",
      expectedGeneration: 9,
      nowMs: Date.parse("2026-08-20T12:00:00Z")
    });

    expect(result.applied).toBe(false);
    expect(result.entry).toMatchObject({
      status: "stopping",
      phase: "stopping",
      desiredState: "closed",
      spawnPid: 4242,
      windowPid: 4343,
      portLeaseStatus: "held"
    });
  });

  it("does not mark a stale start failed while a registered backend handle remains", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "starting",
          phase: "starting",
          desiredState: "open",
          generation: 9,
          spawnPid: 4242,
          port: 8010,
          portLeaseStatus: "held",
          deadlineAt: "2026-08-20T11:59:00Z"
        }
      }
    });

    const result = applyReclaimStaleInFlightStart(payload, {
      instanceId: "worktree:task",
      expectedGeneration: 9,
      nowMs: Date.parse("2026-08-20T12:00:00Z")
    });

    expect(result.applied).toBe(false);
    expect(result.entry).toMatchObject({
      status: "starting",
      spawnPid: 4242,
      portLeaseStatus: "held"
    });
  });

  it("keeps a stopping row busy while its owner lease is still valid", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "stopping",
          phase: "stopping",
          desiredState: "closed",
          generation: 9,
          spawnPid: 4242,
          deadlineAt: "2026-08-20T11:59:00Z",
          ownerLease: { ownerId: "pid:111", expiresAt: "2026-08-20T12:01:00Z" }
        }
      }
    });

    const result = applyReclaimStaleInFlightStart(payload, {
      instanceId: "worktree:task",
      nowMs: Date.parse("2026-08-20T12:00:00Z")
    });

    expect(result.applied).toBe(false);
    expect(result.entry.status).toBe("stopping");
    expect(result.entry.spawnPid).toBe(4242);
  });

  it("discards stale-stop reclaim when the generation no longer matches", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "stopping",
          phase: "stopping",
          desiredState: "closed",
          generation: 9,
          spawnPid: 4242,
          deadlineAt: "2026-08-20T11:59:00Z"
        }
      }
    });

    const result = applyReclaimStaleInFlightStart(payload, {
      instanceId: "worktree:task",
      expectedGeneration: 8,
      nowMs: Date.parse("2026-08-20T12:00:00Z")
    });

    expect(result.applied).toBe(false);
    expect(result.entry).toMatchObject({ status: "stopping", generation: 9, spawnPid: 4242 });
  });

  it("refreshes the stop deadline so an old start deadline cannot release a live stop", () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "steady",
          phase: "steady",
          desiredState: "open",
          generation: 4,
          deadlineAt: "2026-08-20T11:59:00Z",
          inFlightDeadlineAt: "2026-08-20T11:59:00Z"
        }
      }
    });
    const nowMs = Date.parse("2026-08-20T12:00:00Z");

    const claimed = applyClaimStop(payload, { instanceId: "worktree:task", nowMs });
    const reclaimed = applyReclaimStaleInFlightStart(payload, {
      instanceId: "worktree:task",
      nowMs: nowMs + 1_000
    });

    expect(claimed.entry.status).toBe("stopping");
    expect(claimed.entry.deadlineAt).toBe("2026-08-20T12:03:00Z");
    expect(reclaimed.applied).toBe(false);
    expect(reclaimed.entry.status).toBe("stopping");
  });

  it("reclaims all stale stops in one registry-lock transaction", async () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-stale-stops-"));
    tempDirs.push(dir);
    const registryPath = join(dir, "instances.json");
    const { writeFileSync } = await import("node:fs");
    writeFileSync(registryPath, `${JSON.stringify(cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:stale": {
          status: "stopping",
          phase: "stopping",
          desiredState: "closed",
          generation: 2,
          spawnPid: 2002,
          windowPid: 3002,
          portLeaseStatus: "held",
          deadlineAt: "2026-08-20T11:59:00Z"
        },
        "worktree:busy": {
          status: "stopping",
          phase: "stopping",
          desiredState: "closed",
          generation: 3,
          spawnPid: 2003,
          deadlineAt: "2026-08-20T11:59:00Z",
          ownerLease: { ownerId: "pid:303", expiresAt: "2026-08-20T12:01:00Z" }
        }
      }
    }), null, 2)}\n`, "utf8");

    const result = await reclaimStaleInFlightStops(registryPath, {
      nowMs: Date.parse("2026-08-20T12:00:00Z"),
      completionProof: (instanceId) => instanceId === "worktree:stale"
    });

    expect(result).toEqual({ applied: true, instanceIds: ["worktree:stale"] });
    const persisted = JSON.parse(readFileSync(registryPath, "utf8")) as RegistryPayload;
    expect(persisted.instances["worktree:stale"]).toMatchObject({
      status: "closed",
      generation: 2,
      spawnPid: 0,
      windowPid: 0,
      portLeaseStatus: "reclaimable"
    });
    expect(persisted.instances["worktree:busy"]).toMatchObject({
      status: "stopping",
      generation: 3,
      spawnPid: 2003
    });
  });

  it("rejects a persisted start claim while cleanup holds the registry fence", async () => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-cleanup-fence-"));
    tempDirs.push(dir);
    const registryPath = join(dir, "instances.json");
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:task": {
          status: "steady",
          phase: "ready",
          generation: 7,
          cleanupInProgress: true,
          port: 8000,
          controlPort: 8765
        }
      }
    });
    const { writeFileSync } = await import("node:fs");
    writeFileSync(registryPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

    const result = await claimStart(registryPath, {
      instanceId: "worktree:task",
      projectRoot: "C:/worktree/task",
      commandId: "start-1",
      deadlineAt: "2026-08-21T12:30:00Z",
      ownerPid: 1234,
      nowMs: Date.parse("2026-08-21T12:00:00Z"),
      portIsFree: () => {
        throw new Error("cleanup-fenced start must not allocate ports");
      }
    });

    expect(result).toEqual({
      ok: false,
      code: "instance_busy",
      instanceId: "worktree:task",
      status: "cleanup",
      generation: 7
    });
    const persisted = JSON.parse(readFileSync(registryPath, "utf8")) as RegistryPayload;
    expect(persisted.instances["worktree:task"]).toMatchObject({
      status: "steady",
      generation: 7,
      cleanupInProgress: true,
      port: 8000,
      controlPort: 8765
    });
  });
});
