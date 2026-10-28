import { mkdirSync, mkdtempSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import type { AssistantProjectRegistrySnapshot } from "../src/assistant/projectRegistry.js";

const roots: string[] = [];
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
    });
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
    });
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
