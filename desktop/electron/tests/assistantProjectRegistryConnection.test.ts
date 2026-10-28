import { mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { buildSync } from "esbuild";
import { writeLauncherStateFile } from "../src/process/workbenchBackend.js";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import type { AssistantProjectRegistrySnapshot } from "../src/assistant/projectRegistry.js";

const roots: string[] = [];
const sourceLease = (verified = true) => ({ check: async () => true, verifyReceipt: async () => verified, release: async () => undefined });
const deferred = () => {
  let resolve!: () => void;
  const promise = new Promise<void>(done => { resolve = done; });
  return { promise, resolve };
};
function fixture() {
  const root = mkdtempSync(join(tmpdir(), "assistant-registry-connection-")); roots.push(root);
  const filePath = join(root, "assistant", "projects.json");
  const directory = (name: string) => {
    const path = join(root, name); mkdirSync(join(path, ".vibelution"), { recursive: true });
    writeFileSync(join(path, ".vibelution", "project.json"), JSON.stringify({ projectId: "same-project" }));
    return path;
  };
  const integrationRoot = directory("integration");
  const row = (path: string, id = "worktree:task", checkedOut = true) => ({ id, path, checkedOut, alive: false });
  const payload = (items: unknown[], group = integrationRoot) => ({ schemaVersion: 1, integrationRoot: group, items });
  const connection = new AssistantProjectRegistryConnection(filePath);
  const host = { start: vi.fn(async () => undefined), stop: vi.fn(async () => undefined), updateProjects: vi.fn(async (_snapshot: AssistantProjectRegistrySnapshot) => undefined) };
  return { root, filePath, directory, integrationRoot, row, payload, connection, host };
}
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("main-owned assistant registry connection", () => {
  it("retries the same retained host after migration startup fails", async () => {
    const f = fixture();
    const host = { ...f.host, startForMigration: vi.fn().mockRejectedValueOnce(new Error("not ready")).mockResolvedValueOnce(undefined) };
    await expect(f.connection.start(() => host, { migration: true })).rejects.toThrow("not ready");
    await expect(f.connection.start(() => ({ ...host }), { migration: true })).rejects.toThrow("ASSISTANT_ALREADY_STARTED");
    await expect(f.connection.start(() => host, { migration: true })).resolves.toBe(host);
    expect(host.startForMigration).toHaveBeenCalledTimes(2);
    expect(host.stop).not.toHaveBeenCalled();
    await f.connection.stop();
  });

  it("fences reconciliation and waits for an admitted host writer during a migration transition", async () => {
    const f = fixture(), project = f.directory("migration-gate"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.start(() => f.host);
    const writer = f.connection.withHistoryImport(id, async () => { entered.resolve(); await release.promise; });
    await entered.promise;
    const gate = f.connection.beginMigrationTransition();
    let drained = false;
    void gate.drained.then(() => { drained = true; });
    const reconcile = f.connection.reconcile(f.payload([]));
    await Promise.resolve();
    expect(drained).toBe(false);
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    release.resolve();
    await writer;
    await gate.drained;
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    gate.release();
    await reconcile;
    expect(f.host.updateProjects).toHaveBeenCalledOnce();
    await f.connection.stop();
  });

  it("keeps the host attached until retirement is confirmed and holds the source lease through the writer", async () => {
    const f = fixture(), project = f.directory("migration"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    const host = { ...f.host, retireForMigration: vi.fn().mockResolvedValueOnce(false).mockResolvedValueOnce(true) };
    await f.connection.start(() => host);
    expect(await f.connection.retireHostForMigration()).toBe(false);
    await expect(f.connection.withPreHostSource(id, async () => undefined)).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    expect(await f.connection.retireHostForMigration()).toBe(true);
    const writer = f.connection.withPreHostSource(id, async lease => {
      entered.resolve();
      await lease.commit(async () => { await release.promise; });
    }, { operationId: "initial-" + "1".repeat(40), receiptConfirmed: () => true });
    await entered.promise;
    const restarted = f.connection.start(() => host);
    await Promise.resolve();
    expect(host.start).toHaveBeenCalledTimes(1);
    release.resolve();
    await writer;
    await restarted;
    expect(host.start).toHaveBeenCalledTimes(2);
    await f.connection.stop();
  });

  it("holds a pre-host source lease across identical observations and serializes startup", async () => {
    const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    let checkAfterReturn!: () => void;
    const work = f.connection.withPreHostSource(id, async lease => {
      expect(lease.revision).toBe(1);
      expect(lease.registration.root).toBe(f.connection.registration(id)?.root);
      expect(Object.isFrozen(lease.registration)).toBe(true);
      checkAfterReturn = lease.check;
      entered.resolve(); await release.promise;
      expect(lease.signal.aborted).toBe(false);
      lease.check();
      return "done";
    });
    await entered.promise;
    const unchanged = f.connection.reconcile(f.payload([f.row(project)]));
    const starting = f.connection.start(() => f.host);
    await Promise.resolve();
    expect(f.host.start).not.toHaveBeenCalled();
    release.resolve();
    await expect(work).resolves.toBe("done");
    expect(checkAfterReturn).toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await unchanged; await starting;
    expect(f.host.start).toHaveBeenCalledTimes(1);
    await f.connection.stop();
  });

  it("revokes an in-flight lease on a changed or unprovable observation before a commit", async () => {
    for (const mode of ["removed", "unprovable", "malformed"]) {
      const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
      await f.connection.reconcile(f.payload([f.row(project)]));
      const id = Object.keys(f.connection.snapshot().projects)[0];
      let committed = false, signal!: AbortSignal;
      const work = f.connection.withPreHostSource(id, async lease => {
        signal = lease.signal; entered.resolve(); await release.promise;
        lease.check(); committed = true;
      });
      const checked = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
      await entered.promise;
      if (mode === "unprovable") rmSync(project, { recursive: true });
      const observation = f.connection.reconcile(mode === "malformed" ? null : f.payload(mode === "removed" ? [] : [f.row(project)]));
      const observationChecked = mode === "malformed" ? expect(observation).rejects.toThrow("ASSISTANT_INVENTORY_INVALID") : expect(observation).resolves.toBeUndefined();
      expect(signal.aborted).toBe(true);
      release.resolve(); await checked; await observationChecked;
      expect(committed).toBe(false);
      await f.connection.stop();
    }
  });

  it("immediately revokes a pre-host lease when stopped", async () => {
    const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    let signal!: AbortSignal;
    const work = f.connection.withPreHostSource(id, async lease => {
      signal = lease.signal; entered.resolve(); await release.promise; lease.check();
    });
    const checked = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await entered.promise;
    const stopped = f.connection.stop();
    expect(signal.aborted).toBe(true);
    release.resolve(); await checked; await stopped;
  });

  it("waits for an admitted writer to drain before stopping the source lease", async () => {
    const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    let signal!: AbortSignal, drained = false, stopped = false;
    const work = f.connection.withPreHostSource(id, async lease => {
      signal = lease.signal;
      return await lease.commit(async () => { entered.resolve(); await release.promise; drained = true; return "receipt"; });
    }, { operationId: "initial-" + "2".repeat(40), receiptConfirmed: () => true });
    const checked = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await entered.promise;
    const stopping = f.connection.stop().then(() => { stopped = true; });
    await Promise.resolve();
    expect(signal.aborted).toBe(false);
    expect(stopped).toBe(false);
    release.resolve(); await checked; await stopping;
    expect(drained).toBe(true);
    expect(stopped).toBe(true);
    expect(signal.aborted).toBe(true);
  });

  it("latches malformed inventory until a later trusted reconciliation after the writer drains", async () => {
    const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    let signal!: AbortSignal, drained = false;
    const work = f.connection.withPreHostSource(id, async lease => {
      signal = lease.signal;
      return await lease.commit(async () => { entered.resolve(); await release.promise; drained = true; return "result"; });
    }, { operationId: "initial-" + "3".repeat(40), receiptConfirmed: () => true });
    const workRejected = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await entered.promise;
    const older = f.connection.reconcile(f.payload([f.row(project)]));
    const olderRejected = expect(older).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await expect(f.connection.reconcile(null)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    expect(signal.aborted).toBe(false);
    expect(() => f.connection.snapshot()).toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    const after = f.connection.withPreHostSource(id, async () => "must not run");
    const afterRejected = expect(after).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    release.resolve();
    await workRejected; await olderRejected; await afterRejected;
    expect(drained).toBe(true);
    expect(signal.aborted).toBe(true);
    await expect(f.connection.withPreHostSource(id, async () => "must not run")).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await f.connection.reconcile(f.payload([f.row(project)]));
    await expect(f.connection.recoverPreHostSource("initial-" + "3".repeat(40), async () => sourceLease())).resolves.toBe(false);
    await expect(f.connection.withPreHostSource(id, async () => "must remain blocked")).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await f.connection.stop();
  });

  it("persists the original writer before permit and resumes only after fresh source and receipt proof", async () => {
    const f = fixture(), project = f.directory("restart-marker"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0], operationId = "initial-" + "a".repeat(40);
    const markerPath = `${f.filePath}.prehost-recovery.json`;
    const writer = f.connection.withPreHostSource(id, async lease => {
      expect(JSON.parse(readFileSync(markerPath, "utf8")).operationId).toBe(operationId);
      return await lease.commit(async () => { entered.resolve(); await release.promise; return { state: "unknown" }; });
    }, { operationId, receiptConfirmed: value => value.state === "completed" });
    const checked = expect(writer).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await entered.promise;
    await expect(f.connection.reconcile(null)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    release.resolve(); await checked;
    const bundle = join(f.root, "recovery-check.mjs");
    buildSync({ stdin: { resolveDir: process.cwd(), sourcefile: "recovery-check.ts", contents: `
      import {AssistantProjectRegistryConnection} from ${JSON.stringify(join(process.cwd(), "src/assistant/projectRegistryConnection.ts"))};
      const connection=new AssistantProjectRegistryConnection(${JSON.stringify(f.filePath)});let suspended=false;
      await connection.start((_snapshot,value)=>{suspended=value;return {start:async()=>{},stop:async()=>{},updateProjects:async()=>{}};});
      process.stdout.write(JSON.stringify({suspended,pending:connection.pendingPreHostRecovery()}));await connection.stop();
    ` }, bundle: true, platform: "node", format: "esm", outfile: bundle, logLevel: "silent" });
    const child = spawnSync(process.execPath, [bundle], { cwd: f.root, encoding: "utf8", windowsHide: true, timeout: 10000 });
    expect(child.status, child.stderr).toBe(0);
    expect(JSON.parse(child.stdout)).toEqual({ suspended: true, pending: { projectId: id, operationId } });
    const next = new AssistantProjectRegistryConnection(f.filePath);
    expect(next.pendingPreHostRecovery()).toEqual({ projectId: id, operationId });
    const recoveryHost = { ...f.host, suspendProjects: vi.fn(async () => undefined) };
    const factory = vi.fn((_snapshot: AssistantProjectRegistrySnapshot, _suspended: boolean) => recoveryHost);
    await next.start(factory);
    expect(factory).toHaveBeenCalledWith(expect.anything(), true);
    await expect(next.recoverPreHostSource(operationId, async () => sourceLease())).resolves.toBe(false);
    await next.reconcile(f.payload([f.row(project)]));
    await expect(next.recoverPreHostSource(operationId, async () => sourceLease(false))).resolves.toBe(false);
    await expect(next.recoverPreHostSource(operationId, async () => null)).resolves.toBe(false);
    await expect(next.recoverPreHostSource(operationId, async () => sourceLease())).resolves.toBe(false);
    expect(next.pendingPreHostRecovery()?.operationId).toBe(operationId);
    expect(recoveryHost.updateProjects).not.toHaveBeenCalled();
    await next.stop(); await f.connection.stop();
  });

  it("keeps the original marker until deletion is atomically ordered with source and inventory revocation", async () => {
    const f = fixture(), project = f.directory("verifier-lease"), operationId = "ksync-" + "f".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.withPreHostSource(id, lease => lease.commit(async () => "unknown"),
      { operationId, receiptConfirmed: () => false });
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    await connection.reconcile(f.payload([f.row(project)]));
    const acquire = vi.fn(async () => sourceLease());
    expect(await connection.recoverPreHostSource(operationId, acquire)).toBe(false);
    expect(acquire).toHaveBeenCalledOnce();
    expect(connection.pendingPreHostRecovery()?.operationId).toBe(operationId);
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    await restarted.stop(); await connection.stop(); await f.connection.stop();
  });

  it("writes a durable pending record before an isolated verifier commits and never opens the host", async () => {
    const f = fixture(), project = f.directory("commit-proof"), operationId = "initial-" + "a".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.withPreHostSource(id, lease => lease.commit(async () => "unknown"), { operationId, receiptConfirmed: () => false });
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    await connection.reconcile(f.payload([f.row(project)]));
    const release = vi.fn(async () => undefined), commitMarker = vi.fn(async input => {
      input.checkAuthority();
      const pending = JSON.parse(readFileSync(input.markerPath + ".commit-pending", "utf8"));
      expect(pending).toMatchObject({ projectId: id, operationId, markerSha256: input.markerSha256, state: "pending" });
      unlinkSync(input.markerPath);
      return true;
    });
    expect(await connection.recoverPreHostSource(operationId, async () => ({ ...sourceLease(), commitMarker, release }))).toBe(false);
    expect(commitMarker).toHaveBeenCalledOnce(); expect(release).toHaveBeenCalledOnce();
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    expect(restarted.pendingPreHostRecovery()).toEqual({ projectId: id, operationId });
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    await restarted.stop(); await connection.stop(); await f.connection.stop();
  });

  it.each(["inventory", "admission"])("durably revokes the exact commit when %s changes during verifier work", async reason => {
    const f = fixture(), project = f.directory("commit-revoke"), operationId = "initial-" + "b".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.withPreHostSource(id, lease => lease.commit(async () => "unknown"), { operationId, receiptConfirmed: () => false });
    const entered = deferred(), releaseCommit = deferred(), release = vi.fn(async () => undefined);
    const gate = { abandoned: false, check: vi.fn(), release: vi.fn() };
    const connection = new AssistantProjectRegistryConnection(f.filePath, { acquireRecoveryCommitGate: () => gate });
    await connection.reconcile(f.payload([f.row(project)]));
    const work = connection.recoverPreHostSource(operationId, async () => ({ ...sourceLease(), release,
      commitMarker: async input => { entered.resolve(); await releaseCommit.promise; input.checkAuthority(); return true; } }));
    await entered.promise;
    if (reason === "inventory") await expect(connection.reconcile(null)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    else connection.revokePreHostRecovery();
    expect(JSON.parse(readFileSync(`${f.filePath}.prehost-recovery.json.revoked`, "utf8")).reason).toBe("revoked");
    releaseCommit.resolve(); expect(await work).toBe(false);
    expect(release).toHaveBeenCalledOnce();
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    await restarted.stop(); await connection.stop(); await f.connection.stop();
  });

  it("keeps registry reconciliation queued while a busy verifier gate and its Job drain", async () => {
    const f = fixture(), project = f.directory("commit-busy"), operationId = "initial-" + "c".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.withPreHostSource(id, lease => lease.commit(async () => "unknown"), { operationId, receiptConfirmed: () => false });
    const entered = deferred(), commitFinish = deferred(), jobDrain = deferred();
    let busy = true, drained = false;
    const gate = { abandoned: false, check: vi.fn(), release: vi.fn() };
    const connection = new AssistantProjectRegistryConnection(f.filePath, { acquireRecoveryCommitGate: () => busy ? null : gate });
    await connection.reconcile(f.payload([f.row(project)]));
    const work = connection.recoverPreHostSource(operationId, async () => ({ ...sourceLease(),
      release: async () => { await jobDrain.promise; drained = true; },
      commitMarker: async () => { entered.resolve(); await commitFinish.promise; return true; } }));
    await entered.promise;
    const observation = connection.reconcile(f.payload([f.row(project)]));
    let reconciled = false; void observation.then(() => { reconciled = true; });
    commitFinish.resolve(); await Promise.resolve();
    expect(reconciled).toBe(false); expect(drained).toBe(false);
    busy = false; jobDrain.resolve();
    expect(await work).toBe(false); await observation;
    expect(drained).toBe(true);
    expect(JSON.parse(readFileSync(`${f.filePath}.prehost-recovery.json.revoked`, "utf8")).reason).toBe("revoked");
    const acquireAgain = vi.fn(async () => sourceLease());
    expect(await connection.recoverPreHostSource(operationId, acquireAgain)).toBe(false);
    expect(acquireAgain).not.toHaveBeenCalled();
    await connection.stop(); await f.connection.stop();
  });

  it("does not start a marker commit if stop wins during verifier acquisition", async () => {
    const f = fixture(), project = f.directory("commit-stop"), operationId = "initial-" + "d".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await f.connection.withPreHostSource(id, lease => lease.commit(async () => "unknown"), { operationId, receiptConfirmed: () => false });
    const connection = new AssistantProjectRegistryConnection(f.filePath), entered = deferred(), finish = deferred();
    await connection.reconcile(f.payload([f.row(project)]));
    const release = vi.fn(async () => undefined), commitMarker = vi.fn(async () => true);
    const work = connection.recoverPreHostSource(operationId, async () => { entered.resolve(); await finish.promise;
      return { ...sourceLease(), release, commitMarker }; });
    await entered.promise; const stopping = connection.stop(); finish.resolve();
    expect(await work).toBe(false); await stopping;
    expect(release).toHaveBeenCalledOnce(); expect(commitMarker).not.toHaveBeenCalled();
    expect(readFileSync(`${f.filePath}.prehost-recovery.json`, "utf8")).toContain(operationId);
    await f.connection.stop();
  });

  it.each([".commit-pending", ".revoked"])("starts suspended when only an unresolved %s sidecar survives", async suffix => {
    const f = fixture(), project = f.directory("surviving-sidecar");
    await f.connection.reconcile(f.payload([f.row(project)]));
    writeFileSync(`${f.filePath}.prehost-recovery.json${suffix}`, "unconfirmed");
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    await restarted.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    expect(readFileSync(`${f.filePath}.prehost-recovery.json${suffix}`, "utf8")).toBe("unconfirmed");
    await restarted.stop(); await f.connection.stop();
  });

  it("retains the original project and operation ID from a surviving pending commit", async () => {
    const f = fixture(), project = f.directory("pending-identity"), operationId = "affairs-" + "a".repeat(40);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const projectId = Object.keys(f.connection.snapshot().projects)[0];
    const pendingPath = `${f.filePath}.prehost-recovery.json.commit-pending`;
    writeFileSync(pendingPath, JSON.stringify({ schemaVersion: 1, projectId, revision: 1, operationId,
      markerSha256: "c".repeat(64), state: "pending" }));
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    expect(restarted.pendingPreHostRecovery()).toEqual({ projectId, operationId });
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    expect(readFileSync(pendingPath, "utf8")).toContain(operationId);
    await restarted.stop(); await f.connection.stop();
  });

  it("clears an owned marker after the writer drains with a confirmed original receipt", async () => {
    const f = fixture(), project = f.directory("normal-marker");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0], operationId = "initial-" + "b".repeat(40);
    const result = await f.connection.withPreHostSource(id, async lease => await lease.commit(async () => ({ state: "completed" })),
      { operationId, receiptConfirmed: value => value.state === "completed" });
    expect(result.state).toBe("completed");
    const next = new AssistantProjectRegistryConnection(f.filePath);
    expect(next.pendingPreHostRecovery()).toBeNull();
    await next.start((_snapshot, suspended) => { expect(suspended).toBe(false); return f.host; });
    await next.stop(); await f.connection.stop();
  });

  it("never grants a pre-host write permit without a durable original operation marker", async () => {
    const f = fixture(), project = f.directory("missing-marker");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0], mutate = vi.fn(async () => undefined);
    await expect(f.connection.withPreHostSource(id, lease => lease.commit(mutate))).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    expect(mutate).not.toHaveBeenCalled();
    await f.connection.stop();
  });

  it("latches a revoke that arrives while its marker is being published", async () => {
    const f = fixture(), project = f.directory("marker-publication"), writing = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0], operationId = "initial-" + "d".repeat(40);
    const connection = new AssistantProjectRegistryConnection(f.filePath, { writeRecoveryMarker: async (path, marker) => {
      writing.resolve(); await release.promise; await writeLauncherStateFile(path, marker);
    } });
    const callback = vi.fn(async () => undefined);
    const work = connection.withPreHostSource(id, callback, { operationId, receiptConfirmed: () => true });
    const rejected = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await writing.promise;
    await expect(connection.reconcile(null)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    release.resolve(); await rejected;
    expect(callback).not.toHaveBeenCalled();
    expect(connection.pendingPreHostRecovery()).toEqual({ projectId: id, operationId });
    const restarted = new AssistantProjectRegistryConnection(f.filePath);
    await restarted.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    await restarted.stop(); await connection.stop(); await f.connection.stop();
  });

  it("revokes a pre-host lease when the registered directory is replaced at the same path", async () => {
    const f = fixture(), project = f.directory("pre-host"), entered = deferred(), release = deferred();
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    let signal!: AbortSignal, committed = false;
    const work = f.connection.withPreHostSource(id, async lease => {
      signal = lease.signal; entered.resolve(); await release.promise;
      lease.check(); committed = true;
    });
    const checked = expect(work).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await entered.promise;
    renameSync(project, join(f.root, "original-project"));
    f.directory("pre-host");
    const observation = f.connection.reconcile(f.payload([f.row(project)]));
    expect(signal.aborted).toBe(true);
    release.resolve(); await checked; await observation;
    expect(committed).toBe(false);
    await f.connection.stop();
  });

  it("rejects same-path replacement on final check without an inventory observation", async () => {
    const f = fixture(), project = f.directory("pre-host");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await expect(f.connection.withPreHostSource(id, async () => {
      renameSync(project, join(f.root, "original-project"));
      f.directory("pre-host");
      return "not confirmed";
    })).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await f.connection.stop();
  });

  it("rejects existing hosts and suspended registries without invoking the callback", async () => {
    const f = fixture(), project = f.directory("pre-host");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    const callback = vi.fn(async () => undefined);
    await f.connection.start(() => f.host);
    await expect(f.connection.withPreHostSource(id, callback)).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    expect(callback).not.toHaveBeenCalled();
    await f.connection.stop();
    rmSync(project, { recursive: true });
    const suspended = new AssistantProjectRegistryConnection(f.filePath);
    await expect(suspended.withPreHostSource(id, callback)).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    expect(callback).not.toHaveBeenCalled();
    await suspended.stop();
  });

  it("propagates a callback failure without closing an unchanged connection and detects registry tampering", async () => {
    const f = fixture(), project = f.directory("pre-host");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    await expect(f.connection.withPreHostSource(id, async () => { throw new Error("CALLBACK_FAILED"); })).rejects.toThrow("CALLBACK_FAILED");
    await expect(f.connection.withPreHostSource(id, async lease => { lease.check(); return "retry"; })).resolves.toBe("retry");
    await expect(f.connection.withPreHostSource(id, async () => {
      writeFileSync(f.filePath, "{tampered");
      return "must not return";
    })).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await f.connection.stop();
  });

  it("serializes project revocation until the history operation settles", async () => {
    const f = fixture(), project = f.directory("history-project"), gate = deferred();
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const id = Object.keys(f.connection.snapshot().projects)[0];
    const importPromise = f.connection.withHistoryImport(id, async revision => {
      expect(revision).toBe(1);
      await gate.promise;
      return "done";
    });
    const revoke = f.connection.reconcile(f.payload([]));
    await Promise.resolve();
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
    gate.resolve();
    await expect(importPromise).resolves.toBe("done");
    await revoke;
    expect(f.host.updateProjects).toHaveBeenCalledTimes(2);
    await expect(f.connection.withHistoryImport(id, async () => undefined)).rejects.toThrow("ASSISTANT_PROJECT_UNAVAILABLE");
    await f.connection.stop();
  });
  it("starts standalone with a suspended full snapshot while strict reads still fail", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const before = f.connection.snapshot(), bytes = readFileSync(f.filePath, "utf8");
    rmSync(project, { recursive: true });
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    const factory = vi.fn((_snapshot: AssistantProjectRegistrySnapshot, _suspended: boolean) => f.host);
    await connection.start(factory);
    expect(factory).toHaveBeenCalledWith(before, true);
    expect(() => connection.snapshot()).toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    expect(readFileSync(f.filePath, "utf8")).toBe(bytes);
    await connection.stop();
  });

  it("clears startup suspension through a full unchanged snapshot after roots recover", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const before = f.connection.snapshot(), bytes = readFileSync(f.filePath, "utf8");
    rmSync(project, { recursive: true });
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    await connection.start((_snapshot, suspended) => { expect(suspended).toBe(true); return f.host; });
    f.directory("task");
    await connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects).toHaveBeenCalledExactlyOnceWith(before);
    expect(readFileSync(f.filePath, "utf8")).toBe(bytes);
    await connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
    await connection.stop();
  });

  it("suspends project authority after inventory failure, retains chat, and still stops the retained host", async () => {
    const f = fixture(), project = f.directory("task");
    const suspendProjects = vi.fn(async () => undefined);
    const host = { ...f.host, suspendProjects };
    await f.connection.start(() => host);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const bytes = readFileSync(f.filePath, "utf8");
    rmSync(f.integrationRoot, { recursive: true });
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow();
    expect(suspendProjects).toHaveBeenCalledTimes(1);
    expect(host.stop).not.toHaveBeenCalled();
    expect(readFileSync(f.filePath, "utf8")).toBe(bytes);
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    await expect(f.connection.start(() => host)).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    await f.connection.stop();
    expect(host.stop).toHaveBeenCalledTimes(1);
  });

  it("retires a host when project suspension is unconfirmed", async () => {
    const f = fixture();
    const suspendProjects = vi.fn(async () => { throw new Error("ASSISTANT_REGISTRY_UNCONFIRMED"); });
    await f.connection.start(() => ({ ...f.host, suspendProjects }));
    rmSync(f.integrationRoot, { recursive: true });
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow();
    expect(suspendProjects).toHaveBeenCalledTimes(1);
    expect(f.host.stop).toHaveBeenCalledTimes(1);
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
  });

  it("suspends without publishing a subset when another integration loses its root", async () => {
    const f = fixture(), a = f.directory("a"), b = f.directory("b");
    const suspendProjects = vi.fn(async () => undefined);
    await f.connection.start(() => ({ ...f.host, suspendProjects }));
    await f.connection.reconcile(f.payload([f.row(a)]));
    await f.connection.reconcile(f.payload([f.row(b)], b));
    const before = f.host.updateProjects.mock.calls[1][0], bytes = readFileSync(f.filePath, "utf8");
    rmSync(b, { recursive: true });
    await expect(f.connection.reconcile(f.payload([f.row(a)]))).rejects.toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    expect(f.host.updateProjects).toHaveBeenCalledTimes(2);
    expect(suspendProjects).toHaveBeenCalledTimes(1);
    expect(readFileSync(f.filePath, "utf8")).toBe(bytes);
    const captured = vi.fn((_snapshot: AssistantProjectRegistrySnapshot, _suspended: boolean) => f.host);
    const next = new AssistantProjectRegistryConnection(f.filePath);
    await next.start(captured);
    expect(captured).toHaveBeenCalledWith(before, true);
    await next.stop();
    await f.connection.stop();
  });

  it("retires legacy hosts without suspension support on inventory failure", async () => {
    const f = fixture();
    await f.connection.start(() => f.host);
    rmSync(f.integrationRoot, { recursive: true });
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow();
    expect(f.host.stop).toHaveBeenCalledTimes(1);
  });

  it("grants checked-out inventory, revokes an authoritative empty group, and re-adds with a new UUID", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(project), f.row("", "branch:inactive", false)]));
    const first = f.host.updateProjects.mock.calls[0][0];
    const id = Object.keys(first.projects)[0];
    expect(id).toMatch(/^same-project:worktree:task:[a-f0-9]{12}:[a-f0-9]{24}:[a-f0-9-]{36}$/);
    expect(Object.values(first.projects)).toEqual([process.platform === "win32" ? realpathSync.native(project).toLowerCase() : realpathSync.native(project)]);
    await f.connection.reconcile(f.payload([]));
    expect(f.host.updateProjects.mock.calls[1][0]).toEqual({ schemaVersion: 1, revision: 2, projects: {} });
    await f.connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects.mock.calls[2][0].projects).not.toHaveProperty(id);
    expect(JSON.parse(readFileSync(f.filePath, "utf8")).registrations.map((r: any) => r.active)).toEqual([false, true]);
  });

  it("loads persisted roots before host.start without native inventory or a workspace", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    const connection = new AssistantProjectRegistryConnection(f.filePath);
    let captured!: AssistantProjectRegistrySnapshot;
    await connection.start(snapshot => { captured = snapshot; expect(f.host.start).not.toHaveBeenCalled(); return f.host; });
    expect(captured.revision).toBe(1);
    expect(Object.values(captured.projects)).toHaveLength(1);
    expect(f.host.start).toHaveBeenCalledTimes(1);
  });

  it("constructs a host from the latest queued inventory and sends only increasing revisions", async () => {
    const f = fixture(), project = f.directory("task");
    const observation = f.connection.reconcile(f.payload([f.row(project)]));
    let captured!: AssistantProjectRegistrySnapshot;
    const startup = f.connection.start(snapshot => { captured = snapshot; return f.host; });
    await Promise.all([observation, startup]);
    expect(captured.revision).toBe(1);
    expect(Object.values(captured.projects)).toHaveLength(1);
    await f.connection.reconcile(f.payload([f.row(project)]));
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    await f.connection.reconcile(f.payload([]));
    expect(f.host.updateProjects.mock.calls[0][0].revision).toBe(2);
  });

  it("namespaces cloned project IDs by physical integration root and preserves other groups", async () => {
    const f = fixture(), a = f.directory("a"), b = f.directory("b");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(a)]));
    await f.connection.reconcile(f.payload([f.row(b)], b));
    expect(Object.keys(f.host.updateProjects.mock.calls[1][0].projects)).toHaveLength(2);
    await f.connection.reconcile(f.payload([]));
    expect(Object.values(f.host.updateProjects.mock.calls[2][0].projects)).toEqual([process.platform === "win32" ? realpathSync.native(b).toLowerCase() : realpathSync.native(b)]);
  });

  it.each([
    null,
    { schemaVersion: 1, integrationRoot: "relative", items: [] },
    { schemaVersion: 1, items: [] },
    "missing-row", "missing-id", "missing-checkedOut", "relative-path", "unchecked-malformed", "duplicate-id",
  ])("rejects malformed inventory without grants, revocation or a host call: %s", async invalid => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    await f.connection.reconcile(f.payload([f.row(project)]));
    const before = readFileSync(f.filePath, "utf8");
    const badRows: Record<string, unknown[]> = {
      "missing-row": [f.row(project), null], "missing-id": [{ checkedOut: true, path: project }],
      "missing-checkedOut": [{ id: "task", path: project }], "relative-path": [f.row("relative")],
      "unchecked-malformed": [{ id: "branch", checkedOut: "false", path: "" }],
      "duplicate-id": [f.row(project), f.row(project)],
    };
    await expect(f.connection.reconcile(typeof invalid === "string" ? f.payload(badRows[invalid]) : invalid)).rejects.toThrow("ASSISTANT_INVENTORY_INVALID");
    expect(readFileSync(f.filePath, "utf8")).toBe(before);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
    expect(f.host.stop).not.toHaveBeenCalled();
  });

  it("serializes startup and each update, and resolves a revocation only after its matching ACK", async () => {
    const f = fixture(), project = f.directory("task"), startup = deferred(), ack = deferred();
    f.host.start.mockImplementation(() => startup.promise);
    const starting = f.connection.start(() => f.host);
    const granting = f.connection.reconcile(f.payload([f.row(project)]));
    await vi.waitFor(() => expect(f.host.start).toHaveBeenCalled());
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    startup.resolve(); await starting; await granting;
    f.host.updateProjects.mockImplementation(() => ack.promise);
    let revoked = false;
    const removing = f.connection.reconcile(f.payload([])).then(() => { revoked = true; });
    await vi.waitFor(() => expect(f.host.updateProjects).toHaveBeenCalledTimes(2));
    const third = f.connection.reconcile(f.payload([f.row(project)]));
    expect(revoked).toBe(false);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(2);
    ack.resolve(); await removing; await third;
    expect(f.host.updateProjects.mock.calls.map(([snapshot]) => snapshot.revision)).toEqual([1, 2, 3]);
  });

  it("retires only its host after an unknown update, and never replays or restarts", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.start(() => f.host);
    f.host.updateProjects.mockRejectedValue(new Error("ASSISTANT_REGISTRY_UNCONFIRMED"));
    await expect(f.connection.reconcile(f.payload([f.row(project)]))).rejects.toThrow("ASSISTANT_REGISTRY_UNCONFIRMED");
    await expect(f.connection.reconcile(f.payload([]))).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    await expect(f.connection.start(() => f.host)).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED");
    expect(f.host.stop).toHaveBeenCalledTimes(1);
    expect(f.host.updateProjects).toHaveBeenCalledTimes(1);
  });

  it("closes admission immediately on shutdown and does not replay a queued observation", async () => {
    const f = fixture(); await f.connection.start(() => f.host);
    const queued = f.connection.reconcile(f.payload([]));
    const stopped = f.connection.stop();
    await expect(queued).rejects.toThrow("ASSISTANT_REGISTRY_CLOSED"); await stopped;
    expect(f.host.updateProjects).not.toHaveBeenCalled();
    expect(f.host.stop).toHaveBeenCalledTimes(1);
  });

  it("retains its owned host for cleanup retry when retirement fails", async () => {
    const f = fixture(); await f.connection.start(() => f.host);
    f.host.stop.mockRejectedValueOnce(new Error("OWNED_JOB_RETIRE_FAILED"));
    await expect(f.connection.stop()).rejects.toThrow("OWNED_JOB_RETIRE_FAILED");
    await f.connection.stop();
    expect(f.host.stop).toHaveBeenCalledTimes(2);
  });

  it("fails closed on corrupt persisted grants and missing roots, and revokes deleted roots on valid inventory", async () => {
    const f = fixture(), project = f.directory("task");
    await f.connection.reconcile(f.payload([f.row(project)]));
    rmSync(project, { recursive: true });
    expect(() => new AssistantProjectRegistryConnection(f.filePath).snapshot()).toThrow("PROJECT_REGISTRY_RECONCILE_REQUIRED");
    await f.connection.reconcile(f.payload([f.row(project)]));
    let snapshot!: AssistantProjectRegistrySnapshot;
    await f.connection.start(value => { snapshot = value; return f.host; });
    expect(snapshot.projects).toEqual({});
    writeFileSync(f.filePath, "{broken");
    expect(() => new AssistantProjectRegistryConnection(f.filePath)).toThrow("PROJECT_REGISTRY_INVALID");
  });
});
