import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";

import {
  applyAdoptLiveInstance,
  applyClaimStart,
  applyClaimStop,
  applyClaimStopIfGeneration,
  applyCloseConfirmedDeadInstance,
  applyCompleteStop,
  applyObserve,
  applyRecordSpawnPid,
  applyReclaimStaleInFlightStart,
  applyRenewOwnerLease,
  applySweepTerminatedRows,
  applyUpsert,
  claimStart,
  claimStop,
  claimStopIfGeneration,
  ownerLeaseOf,
  reclaimStaleInFlightStops,
  readRegistry,
  recordSpawnPid,
  REGISTRY_OBSERVATION_GRACE_MS,
  type RegistryPayload,
  type SweepGraceTracker
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

  it("holds the allocated ports while a new backend is still starting", async () => {
    const payload = cloneRegistry({
      schemaVersion: 3,
      instances: {
        "worktree:first": {
          status: "closed",
          desiredState: "closed",
          phase: "steady",
          generation: 1,
          portLeaseStatus: "reclaimable"
        }
      }
    });
    const first = await applyClaimStart(payload, {
      instanceId: "worktree:first",
      projectRoot: "C:/repo/.worktrees/first",
      operation: "start",
      commandId: "start-first",
      deadlineAt: "2026-09-15T00:03:00Z",
      ownerPid: 100,
      preferredBackend: 8000,
      preferredControl: 8765,
      portIsFree: () => true
    });
    const second = await applyClaimStart(payload, {
      instanceId: "worktree:second",
      projectRoot: "C:/repo/.worktrees/second",
      operation: "start",
      commandId: "start-second",
      deadlineAt: "2026-09-15T00:03:00Z",
      ownerPid: 101,
      preferredBackend: 8000,
      preferredControl: 8765,
      portIsFree: () => true
    });

    expect(first.ok).toBe(true);
    expect(second.ok).toBe(true);
    if (!first.ok || !second.ok) {
      throw new Error("start claims unexpectedly failed");
    }
    expect(first.entry.portLeaseStatus).toBe("held");
    expect(second.entry.portLeaseStatus).toBe("held");
    expect(second.entry.port).not.toBe(first.entry.port);
    expect(second.entry.controlPort).not.toBe(first.entry.controlPort);
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

  it.each([
    "{not-json",
    JSON.stringify({ instances: [] }),
    JSON.stringify({ schemaVersion: 3, instances: { "worktree:bad": [] } }),
  ])("fails closed without replacing a corrupt registry", async (contents) => {
    const dir = mkdtempSync(join(tmpdir(), "vibelution-registry-corrupt-"));
    tempDirs.push(dir);
    const registryPath = join(dir, "instances.json");
    writeFileSync(registryPath, contents, "utf8");

    await expect(readRegistry(registryPath)).rejects.toThrow("instances registry is corrupt");
    await expect(claimStart(registryPath, {
      instanceId: "worktree:task",
      projectRoot: "C:/worktree/task",
      commandId: "start-1",
      deadlineAt: "2026-08-21T12:30:00Z",
      ownerPid: 1234,
    })).rejects.toThrow("instances registry is corrupt");
    expect(readFileSync(registryPath, "utf8")).toBe(contents);
  });
});

describe("applyAdoptLiveInstance", () => {
  const baseInput = {
    instanceId: "worktree:adopt",
    projectRoot: "C:/worktree/adopt",
    branch: "codex/adopt",
    observedPid: 4242,
    observedPort: 8001,
    observedControlPort: 8767,
    nowMs: Date.parse("2026-10-02T10:00:00Z")
  };

  it("adopts a terminal closed row onto the observed live backend", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:adopt": {
          port: 8001,
          controlPort: 8767,
          projectRoot: "C:/worktree/adopt",
          status: "closed",
          generation: 4,
          failureMessage: "",
          portLeaseStatus: "reclaimable",
          portLease: { status: "reclaimable", reason: "legacy_unknown_idle" },
          cleanupObservation: { kind: "orphan", firstObservedAt: "2026-08-19T16:28:53Z" }
        }
      }
    };
    const result = applyAdoptLiveInstance(payload, {
      ...baseInput,
      identity: { createTime: 133000000000000000, executable: "pythonw.exe" },
      commandId: "adopt:abc"
    });
    expect(result.applied).toBe(true);
    const entry = payload.instances["worktree:adopt"];
    expect(entry).toMatchObject({
      status: "steady",
      phase: "steady",
      desiredState: "open",
      spawnPid: 4242,
      spawnCreateTime: 133000000000000000,
      spawnExecutable: "pythonw.exe",
      port: 8001,
      controlPort: 8767,
      portLeaseStatus: "held",
      generation: 5,
      commandId: "adopt:abc",
      failureMessage: "",
      url: "http://127.0.0.1:8001"
    });
    expect(entry.portLease).toBeUndefined();
    expect(entry.cleanupObservation).toBeUndefined();
    expect(entry.deadlineAt).toBeUndefined();
    expect(entry.inFlightDeadlineAt).toBeUndefined();
    expect(entry.ownerLease).toBeUndefined();
  });

  it("creates a row when the registry has none", () => {
    const payload: RegistryPayload = { schemaVersion: 3, instances: {} };
    const result = applyAdoptLiveInstance(payload, baseInput);
    expect(result.applied).toBe(true);
    expect(payload.instances["worktree:adopt"]).toMatchObject({
      status: "steady",
      spawnPid: 4242,
      port: 8001,
      controlPort: 8767,
      portLeaseStatus: "held",
      generation: 1
    });
  });

  it("is idempotent when the row already matches the observation", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:adopt": {
          port: 8001,
          controlPort: 8767,
          projectRoot: "C:/worktree/adopt",
          status: "steady",
          phase: "steady",
          desiredState: "open",
          spawnPid: 4242,
          portLeaseStatus: "held",
          generation: 7
        }
      }
    };
    const result = applyAdoptLiveInstance(payload, baseInput);
    expect(result.applied).toBe(false);
    expect(payload.instances["worktree:adopt"].generation).toBe(7);
  });

  it("never adopts an in-flight row owned by a live supervisor", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:adopt": {
          port: 8001,
          status: "starting",
          desiredState: "open",
          generation: 9,
          spawnPid: 0,
          portLeaseStatus: "held"
        }
      }
    };
    const result = applyAdoptLiveInstance(payload, baseInput);
    expect(result.applied).toBe(false);
    expect(payload.instances["worktree:adopt"].status).toBe("starting");
    expect(payload.instances["worktree:adopt"].generation).toBe(9);
  });

  it("refuses to clobber a different live registered spawn pid", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:adopt": {
          port: 8001,
          status: "steady",
          desiredState: "open",
          spawnPid: 111,
          portLeaseStatus: "held",
          generation: 3
        }
      }
    };
    const result = applyAdoptLiveInstance(payload, { ...baseInput, registeredSpawnPidAlive: true });
    expect(result.applied).toBe(false);
    expect(payload.instances["worktree:adopt"].spawnPid).toBe(111);
  });

  it("drops a stale identity triple when the observation has none", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:adopt": {
          port: 8001,
          status: "failed",
          spawnPid: 0,
          spawnCreateTime: 1,
          spawnExecutable: "stale.exe",
          generation: 2
        }
      }
    };
    const result = applyAdoptLiveInstance(payload, baseInput);
    expect(result.applied).toBe(true);
    const entry = payload.instances["worktree:adopt"];
    expect(entry.spawnCreateTime).toBeUndefined();
    expect(entry.spawnExecutable).toBeUndefined();
    expect(entry.status).toBe("steady");
  });

  it("rejects observations without a live pid or port", () => {
    const payload: RegistryPayload = { schemaVersion: 3, instances: {} };
    expect(() => applyAdoptLiveInstance(payload, { ...baseInput, observedPid: 0 })).toThrow();
    expect(() => applyAdoptLiveInstance(payload, { ...baseInput, observedPort: 0 })).toThrow();
  });
});

describe("applyCloseConfirmedDeadInstance", () => {
  const t0 = Date.parse("2026-10-02T10:00:00Z");

  it("settles a dead steady row to closed and reclaims the lease", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:dead": {
          port: 8002,
          status: "steady",
          desiredState: "open",
          spawnPid: 999,
          spawnCreateTime: 5,
          spawnExecutable: "pythonw.exe",
          portLeaseStatus: "held",
          generation: 7
        }
      }
    };
    const result = applyCloseConfirmedDeadInstance(payload, {
      instanceId: "worktree:dead",
      expectedGeneration: 7,
      outcome: "closed",
      nowMs: t0
    });
    expect(result.applied).toBe(true);
    expect(payload.instances["worktree:dead"]).toMatchObject({
      status: "closed",
      phase: "steady",
      desiredState: "closed",
      spawnPid: 0,
      portLeaseStatus: "reclaimable",
      generation: 7
    });
    expect(payload.instances["worktree:dead"].spawnExecutable).toBeUndefined();
    expect(payload.instances["worktree:dead"].ownerLease).toBeUndefined();
  });

  it("settles a stale in-flight start to failed with the supervisor-lost message", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:stale": {
          port: 8003,
          status: "starting",
          desiredState: "open",
          spawnPid: 555,
          portLeaseStatus: "held",
          generation: 2,
          deadlineAt: "2026-10-02T09:00:00Z",
          inFlightDeadlineAt: "2026-10-02T09:00:00Z"
        }
      }
    };
    const result = applyCloseConfirmedDeadInstance(payload, {
      instanceId: "worktree:stale",
      expectedGeneration: 2,
      outcome: "failed",
      failureMessage: "启动监督进程已退出且超过启动期限，启动未完成。",
      nowMs: t0
    });
    expect(result.applied).toBe(true);
    expect(payload.instances["worktree:stale"]).toMatchObject({
      status: "failed",
      phase: "failed",
      desiredState: "open",
      spawnPid: 0,
      portLeaseStatus: "reclaimable"
    });
  });

  it("honors the generation CAS and refuses mismatched outcomes", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:a": { status: "steady", spawnPid: 10, generation: 5 },
        "worktree:b": { status: "closed", spawnPid: 0, generation: 5 }
      }
    };
    expect(applyCloseConfirmedDeadInstance(payload, {
      instanceId: "worktree:a",
      expectedGeneration: 6,
      outcome: "closed"
    }).applied).toBe(false);
    expect(applyCloseConfirmedDeadInstance(payload, {
      instanceId: "worktree:b",
      outcome: "closed"
    }).applied).toBe(false);
    expect(payload.instances["worktree:a"].spawnPid).toBe(10);
  });
});

describe("applySweepTerminatedRows", () => {
  const t0 = Date.parse("2026-10-02T10:00:00Z");
  const existingRoot = "C:/worktree/alive";

  function sweep(
    payload: RegistryPayload,
    input: Partial<Parameters<typeof applySweepTerminatedRows>[1]> = {}
  ) {
    return applySweepTerminatedRows(payload, {
      nowMs: t0,
      pidAlive: () => false,
      pathExists: (path) => path === existingRoot,
      ...input
    });
  }

  it("removes a dead key after the grace elapses", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:gone": {
          port: 8004,
          status: "closed",
          projectRoot: "C:/worktree/gone",
          generation: 2
        }
      }
    };
    const tracker: SweepGraceTracker = new Map();
    expect(sweep(payload, { graceTracker: tracker }).removedInstanceIds).toEqual([]);
    expect(payload.instances["worktree:gone"]).toBeDefined();
    expect(sweep(payload, {
      graceTracker: tracker,
      nowMs: t0 + REGISTRY_OBSERVATION_GRACE_MS + 1
    }).removedInstanceIds).toEqual(["worktree:gone"]);
    expect(payload.instances["worktree:gone"]).toBeUndefined();
  });

  it("keeps rows whose worktree still exists or whose identity may live", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:exists": { status: "closed", projectRoot: existingRoot },
        "worktree:livepid": { status: "closed", projectRoot: "C:/worktree/gone", spawnPid: 42 },
        "worktree:livewin": { status: "closed", projectRoot: "C:/worktree/gone", windowPid: 43 },
        "worktree:inflight": { status: "stopping", projectRoot: "C:/worktree/gone" },
        "worktree:protected": { status: "failed", projectRoot: "C:/worktree/gone" }
      }
    };
    const result = sweep(payload, {
      nowMs: t0 + REGISTRY_OBSERVATION_GRACE_MS * 10,
      pidAlive: (pid) => pid === 42 || pid === 43,
      protectedInstanceIds: ["worktree:protected"],
      graceTracker: new Map([
        ["worktree:exists", { since: t0, fingerprint: `${existingRoot}|0|0` }],
        ["worktree:livepid", { since: t0, fingerprint: "C:/worktree/gone|0|0" }],
        ["worktree:livewin", { since: t0, fingerprint: "C:/worktree/gone|0|0" }],
        ["worktree:inflight", { since: t0, fingerprint: "C:/worktree/gone|0|0" }],
        ["worktree:protected", { since: t0, fingerprint: "C:/worktree/gone|0|0" }]
      ])
    });
    expect(result.removedInstanceIds).toEqual([]);
    expect(Object.keys(payload.instances)).toHaveLength(5);
  });

  it("resets the grace when the row fingerprint changes", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:churn": { status: "failed", projectRoot: "C:/worktree/gone", generation: 1 }
      }
    };
    const tracker: SweepGraceTracker = new Map([
      ["worktree:churn", { since: t0 - REGISTRY_OBSERVATION_GRACE_MS - 1, fingerprint: "C:/worktree/gone|0|0" }]
    ]);
    const result = sweep(payload, {
      graceTracker: tracker,
      nowMs: t0 + REGISTRY_OBSERVATION_GRACE_MS + 1
    });
    expect(result.removedInstanceIds).toEqual([]);
    expect(result.eligibleInstanceIds).toEqual(["worktree:churn"]);
    expect(tracker.get("worktree:churn")?.fingerprint).toBe("C:/worktree/gone|1|0");
  });

  it("keeps rows with an unexpired owner lease", () => {
    const payload: RegistryPayload = {
      schemaVersion: 3,
      instances: {
        "worktree:leased": {
          status: "closed",
          projectRoot: "C:/worktree/gone",
          ownerLease: { ownerId: "pid:1", expiresAt: new Date(t0 + 60_000).toISOString() }
        }
      }
    };
    const result = sweep(payload, {
      nowMs: t0 + REGISTRY_OBSERVATION_GRACE_MS * 10,
      graceTracker: new Map()
    });
    expect(result.removedInstanceIds).toEqual([]);
    expect(payload.instances["worktree:leased"]).toBeDefined();
  });
});
