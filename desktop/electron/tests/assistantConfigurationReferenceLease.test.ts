import { mkdirSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantProjectRegistry } from "../src/assistant/projectRegistry.js";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import { ConfigurationReferenceLeaseBroker } from "../src/assistant/configurationReferenceLease.js";
import { configurationReferenceResult, type ConfigurationReferenceHostContext, type ConfigurationReferenceSnapshot,
  type ConfigurationReferenceRequest } from "../src/assistant/configurationReferenceProtocol.js";
import { parseMainControlClaim, projectMainControlResult, runMainControlPump } from "../src/assistant/mainControlTransport.js";

const roots: string[] = [];
const aborters: AbortController[] = [];
afterEach(() => { for (const abort of aborters.splice(0)) abort.abort(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
const deferred = () => { let resolve!: () => void; return { promise: new Promise<void>(done => { resolve = done; }), resolve: () => resolve() }; };
const acquire = (context = "a"): ConfigurationReferenceRequest => ({ deliveryId: "1".repeat(32),
  action: "configuration_reference_acquire", contextId: `cfg-${context.repeat(32)}` });
const request = (snapshot: ConfigurationReferenceSnapshot, action: "configuration_reference_validate" | "configuration_reference_release",
  context = "a"): ConfigurationReferenceRequest => ({ deliveryId: "2".repeat(32), action, contextId: `cfg-${context.repeat(32)}`,
    leaseId: snapshot.leaseId, snapshotDigest: snapshot.snapshotDigest });
async function setup() {
  const root = realpathSync.native(mkdtempSync(join(tmpdir(), "configuration-reference-")));
  const canonical = process.platform === "win32" ? root.toLowerCase() : root; roots.push(canonical);
  const active = join(canonical, "active"), inactive = join(canonical, "inactive"), profile = join(canonical, "profile");
  for (const path of [active, inactive, profile]) mkdirSync(path);
  const file = join(canonical, "registry.json"), connection = new AssistantProjectRegistryConnection(file);
  const inventory = { schemaVersion: 1, integrationRoot: active, items: [
    { id: "main", path: active, checkedOut: true }, { id: "worktree:inactive", path: inactive, checkedOut: true }] };
  await connection.reconcile(inventory);
  await connection.reconcile({ ...inventory, items: inventory.items.slice(0, 1) });
  const abort = new AbortController(), drain = deferred();
  aborters.push(abort);
  const host: ConfigurationReferenceHostContext = { generationId: "generation-1", agentId: "native-assistant", sessionId: "native-session",
    nativeAssistantRoot: profile, signal: abort.signal, check: () => { if (abort.signal.aborted) throw new Error("closed"); }, drain: () => drain.promise,
    retainLease: vi.fn(() => vi.fn()), readWorkComplete: vi.fn(async () => false), ackWorkComplete: vi.fn(async () => {}) };
  const broker = new ConfigurationReferenceLeaseBroker(connection);
  return { root: canonical, active, inactive, profile, file, inventory, connection, broker, host, abort, drain };
}

describe("private complete registry reference admission", () => {
  it("returns inactive registrations and the actual native root separately from the admitted project projection", async () => {
    const f = await setup();
    expect(Object.keys(f.connection.snapshot().projects)).toHaveLength(1);
    const snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    expect(snapshot.complete).toBe(true); expect(snapshot.projects).toHaveLength(2);
    expect(snapshot.projects).toContainEqual(expect.objectContaining({ root: f.inactive, active: false }));
    expect(snapshot.nativeAssistantRoot).toBe(f.profile);
    expect(snapshot.projects.every(row => row.root !== f.profile)).toBe(true);
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: true, revision: snapshot.revision });
    snapshot.projects[0].root = "untrusted mutation";
    expect(await f.broker.handle(acquire(), f.host)).not.toEqual(snapshot);
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
  });

  it("holds real connection writes until explicit release, with idempotent reacquire/release", async () => {
    const f = await setup(), snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    const before = readFileSync(f.file, "utf8");
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    await Promise.resolve(); await Promise.resolve();
    expect(applied).toBe(false); expect(readFileSync(f.file, "utf8")).toBe(before);
    expect(await f.broker.handle(acquire(), f.host)).toEqual(snapshot);
    expect(await f.broker.handle(acquire("b"), f.host)).toEqual({ schemaVersion: 1, complete: false, code: "busy" });
    const release = request(snapshot, "configuration_reference_release");
    expect(await f.broker.handle(release, f.host)).toMatchObject({ released: true });
    expect(await f.broker.handle(release, f.host)).toMatchObject({ released: true });
    await pending;
    expect(applied).toBe(true); expect(Object.keys(f.connection.snapshot().projects)).toHaveLength(2);
  });

  it("holds the underlying document owner too, including writes which bypass the connection projection", async () => {
    const f = await setup(), registry = new AssistantProjectRegistry({ filePath: join(f.root, "direct.json") });
    await registry.reconcile(f.active, [{ projectId: "direct", root: f.active, checkedOut: true }]);
    const hold = await registry.acquireDocumentAdmission();
    let applied = false;
    const pending = registry.reconcile(f.active, []).then(() => { applied = true; });
    await Promise.resolve(); await Promise.resolve();
    expect(applied).toBe(false); expect(hold.snapshot.projects).toHaveLength(1); hold.check();
    await expect(registry.acquireDocumentAdmission()).rejects.toThrow("PROJECT_REGISTRY_DOCUMENT_BUSY");
    hold.release(); await pending; expect(applied).toBe(true);
  });

  it("does not let another context or host generation validate/release a live lease", async () => {
    const f = await setup(), snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    const newGeneration = { ...f.host, generationId: "generation-2" };
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), newGeneration)).toMatchObject({ valid: false });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), newGeneration)).toMatchObject({ released: false });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release", "b"), f.host)).toMatchObject({ released: false });
    expect(await f.broker.handle({ ...request(snapshot, "configuration_reference_release"), leaseId: "f".repeat(64) }, f.host)).toMatchObject({ released: false });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: true });
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
  });

  it("invalidates on cancellation immediately and retains the actual write fence until that Job drains", async () => {
    const f = await setup(), snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    f.abort.abort();
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: false });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host)).toMatchObject({ released: false });
    await Promise.resolve(); expect(applied).toBe(false);
    f.drain.resolve(); await pending;
    expect(applied).toBe(true);
  });

  it("does not queue stop behind the lease or a registry mutation waiting on it", async () => {
    const f = await setup(), stopped = deferred();
    await f.connection.start(() => ({ start: async () => {}, updateProjects: async () => {}, stop: async () => {
      f.abort.abort(); stopped.resolve(); await f.drain.promise;
    } }));
    const snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    const waitingWrite = f.connection.reconcile(f.inventory).then(() => "applied", () => "closed");
    const stopping = f.connection.stop();
    await stopped.promise;
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: false });
    f.drain.resolve(); await stopping;
    expect(await waitingWrite).toBe("closed");
  });

  it("fails closed on a changed registry document and can release the old invalid scan scope", async () => {
    const f = await setup(), snapshot = await f.broker.handle(acquire(), f.host) as ConfigurationReferenceSnapshot;
    const changed = JSON.parse(readFileSync(f.file, "utf8")); changed.revision += 1;
    writeFileSync(f.file, JSON.stringify(changed));
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: false });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host)).toMatchObject({ released: true });
    expect(await f.broker.handle(acquire("b"), f.host)).toMatchObject({ complete: false, code: "unavailable" });
  });

  it("closes private protocol fields and never accepts model-supplied roots or public project-result passthrough", async () => {
    const claim = acquire();
    expect(parseMainControlClaim({ schemaVersion: 1, request: claim })).toEqual(claim);
    for (const extra of [{ roots: [] }, { projectId: "other" }, { nativeAssistantRoot: "C:/forged" }, { snapshot: {} }])
      expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...claim, ...extra } })).toThrow("ASSISTANT_MAIN_CONTROL_INVALID");
    const f = await setup(), snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    expect(projectMainControlResult(claim, snapshot)).toEqual(snapshot);
    const ordinary = projectMainControlResult({ deliveryId: "a".repeat(32), action: "project_status", projectId: "a", operation: "status" }, snapshot);
    expect(JSON.stringify(ordinary)).not.toContain(f.profile);
    expect(configurationReferenceResult(request(snapshot, "configuration_reference_validate"), { ...snapshot, valid: true })).toMatchObject({ valid: false });
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
  });

  it.each([false, undefined])("distinguishes a known rejected settle from a lost settle acknowledgement (%s)", async accepted => {
    const f = await setup(), channel = new AbortController(), claim = acquire();
    let claimed = false, snapshot: ConfigurationReferenceSnapshot | undefined;
    const onFailure = vi.fn(() => channel.abort());
    await runMainControlPump({ signal: channel.signal, isCurrent: () => !channel.signal.aborted,
      invoke: async path => {
        if (path.endsWith("/next")) {
          if (!claimed) { claimed = true; return { schemaVersion: 1, request: claim }; }
          return await new Promise((_resolve, reject) => {
            const stop = () => reject(new Error("closed"));
            if (channel.signal.aborted) stop(); else channel.signal.addEventListener("abort", stop, { once: true });
          });
        }
        if (accepted === undefined) throw new Error("settle acknowledgement lost");
        return { schemaVersion: 1, accepted };
      },
      onRequest: async request => { snapshot = await f.broker.handle(request as ConfigurationReferenceRequest, f.host) as ConfigurationReferenceSnapshot; return snapshot; },
      onSettled: (request, value, observed) => {
        f.broker.settled(request as ConfigurationReferenceRequest, value, observed, f.host);
        if (observed === false) channel.abort();
      }, onFailure });
    expect(snapshot?.complete).toBe(true);
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    if (accepted === false) {
      await pending; expect(applied).toBe(true); expect(onFailure).not.toHaveBeenCalled();
      expect(await f.broker.handle(acquire("b"), f.host)).toMatchObject({ complete: true });
      const next = await f.broker.handle(acquire("b"), f.host) as ConfigurationReferenceSnapshot;
      await f.broker.handle(request(next, "configuration_reference_release", "b"), f.host);
    } else {
      await Promise.resolve(); await Promise.resolve(); expect(applied).toBe(false);
      expect(onFailure).toHaveBeenCalledOnce();
      expect(await f.broker.handle(request(snapshot!, "configuration_reference_validate"), f.host)).toMatchObject({ valid: false });
      expect(await f.broker.handle(request(snapshot!, "configuration_reference_release"), f.host)).toMatchObject({ released: false });
      f.drain.resolve(); await pending; expect(applied).toBe(true);
    }
  });

  it("does not release an already delivered lease when a duplicate acquire delivery expires", async () => {
    const f = await setup(), first = acquire();
    const snapshot = await f.broker.handle(first, f.host) as ConfigurationReferenceSnapshot;
    f.broker.settled(first, snapshot, true, f.host);
    const duplicate = { ...first, deliveryId: "f".repeat(32) };
    const repeated = await f.broker.handle(duplicate, f.host);
    f.broker.settled(duplicate, repeated, false, f.host);
    expect(await f.broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: true });
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
  });

  it("clears a failed pending acquisition only after its cancelled generation drains", async () => {
    const f = await setup();
    const acquireDocument = vi.fn().mockRejectedValueOnce(new Error("document acquisition failed"))
      .mockImplementation(() => f.connection.acquireRegistryDocumentAdmission());
    const broker = new ConfigurationReferenceLeaseBroker({ acquireRegistryDocumentAdmission: acquireDocument });
    const pending = broker.handle(acquire(), f.host);
    f.abort.abort();
    expect(await pending).toMatchObject({ complete: false });
    const next = { ...f.host, generationId: "generation-2", signal: new AbortController().signal, check: () => {} };
    expect(await broker.handle(acquire("b"), next)).toMatchObject({ code: "busy" });
    f.drain.resolve();
    let snapshot: ConfigurationReferenceSnapshot | undefined;
    await vi.waitFor(async () => {
      const result = await broker.handle(acquire("b"), next);
      expect(result).toMatchObject({ complete: true }); snapshot = result as ConfigurationReferenceSnapshot;
    });
    await broker.handle(request(snapshot!, "configuration_reference_release", "b"), next);
  });

  it("automatically releases an unknown acquire only after its exact native scope completes", async () => {
    const f = await setup(), claim = acquire();
    const snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    f.broker.settled(claim, snapshot, undefined, f.host);
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    await vi.waitFor(() => expect(f.host.readWorkComplete).toHaveBeenCalledWith(claim.contextId));
    expect(applied).toBe(false);
    expect(await f.broker.handle(claim, f.host)).toMatchObject({ complete: false, code: "unavailable" });
    expect(await f.broker.handle(acquire("b"), f.host)).toMatchObject({ complete: false, code: "busy" });
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host)).toMatchObject({ released: false });
    vi.mocked(f.host.readWorkComplete).mockResolvedValue(true);
    await pending;
    expect(applied).toBe(true);
    await vi.waitFor(() => expect(f.host.ackWorkComplete).toHaveBeenCalledWith(claim.contextId));
    const releaseRetention = vi.mocked(f.host.retainLease).mock.results[0].value;
    expect(releaseRetention).toHaveBeenCalledOnce();
    // The captured Job drain remains unresolved; only this completed scope ended.
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host)).toMatchObject({ released: true });
  });

  it("does not accept another generation's completion or release and retains unknown proofs through abort", async () => {
    const f = await setup(), claim = acquire();
    const snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    vi.mocked(f.host.readWorkComplete).mockRejectedValue(new Error("unknown scope proof"));
    f.broker.settled(claim, snapshot, undefined, f.host);
    const foreign = { ...f.host, generationId: "foreign-generation", readWorkComplete: vi.fn(async () => true) };
    expect(await f.broker.handle(request(snapshot, "configuration_reference_release"), foreign)).toMatchObject({ released: false });
    expect(foreign.readWorkComplete).not.toHaveBeenCalled();
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    await vi.waitFor(() => expect(f.host.readWorkComplete).toHaveBeenCalled());
    expect(applied).toBe(false);
    f.abort.abort(); await Promise.resolve();
    expect(applied).toBe(false);
    f.drain.resolve(); await pending;
    expect(applied).toBe(true);
    expect(f.host.ackWorkComplete).not.toHaveBeenCalled();
  });

  it("retries scope metadata acknowledgement after releasing the completed reservation", async () => {
    const f = await setup(), claim = acquire();
    const snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    vi.mocked(f.host.ackWorkComplete).mockRejectedValueOnce(new Error("ACK lost"));
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
    await expect(f.connection.reconcile(f.inventory)).resolves.toBeUndefined();
    await vi.waitFor(() => expect(f.host.ackWorkComplete).toHaveBeenCalledTimes(2));
    expect(f.host.readWorkComplete).not.toHaveBeenCalled();
    expect(vi.mocked(f.host.retainLease).mock.results[0].value).toHaveBeenCalledOnce();
  });

  it("finishes retention through an ACK tombstone even when a safely evicted scope GET is unknown", async () => {
    const f = await setup(), claim = acquire();
    const snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    vi.mocked(f.host.readWorkComplete).mockResolvedValue(false);
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
    await vi.waitFor(() => expect(f.host.ackWorkComplete).toHaveBeenCalledWith(claim.contextId));
    expect(vi.mocked(f.host.retainLease).mock.results[0].value).toHaveBeenCalledOnce();
    expect(f.host.readWorkComplete).not.toHaveBeenCalled();
  });

  it("never retains a completed scope for a permanently false metadata ACK after tombstone eviction", async () => {
    const f = await setup(), claim = acquire();
    const snapshot = await f.broker.handle(claim, f.host) as ConfigurationReferenceSnapshot;
    vi.mocked(f.host.ackWorkComplete).mockRejectedValue(new Error("ACK tombstone evicted"));
    await f.broker.handle(request(snapshot, "configuration_reference_release"), f.host);
    expect(vi.mocked(f.host.retainLease).mock.results[0].value).toHaveBeenCalledOnce();
    await vi.waitFor(() => expect(f.host.ackWorkComplete).toHaveBeenCalledTimes(2));
    await expect(f.connection.reconcile(f.inventory)).resolves.toBeUndefined();
    const next = await f.broker.handle(acquire("b"), f.host) as ConfigurationReferenceSnapshot;
    expect(next.complete).toBe(true);
    await f.broker.handle(request(next, "configuration_reference_release", "b"), f.host);
  });

  it("keeps a possibly published snapshot when a duplicate acquire check fails before its first ACK", async () => {
    const f = await setup(), document = await f.connection.acquireRegistryDocumentAdmission();
    let readable = true;
    const broker = new ConfigurationReferenceLeaseBroker({ acquireRegistryDocumentAdmission: async () => ({
      ...document, check: () => { if (!readable) throw new Error("document changed"); document.check(); },
    }) });
    const first = acquire();
    const snapshot = await broker.handle(first, f.host) as ConfigurationReferenceSnapshot;
    readable = false;
    expect(await broker.handle({ ...first, deliveryId: "f".repeat(32) }, f.host)).toMatchObject({ code: "unavailable" });
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    await vi.waitFor(() => expect(f.host.readWorkComplete).toHaveBeenCalled());
    expect(applied).toBe(false);
    expect(vi.mocked(f.host.retainLease).mock.results[0].value).not.toHaveBeenCalled();
    expect(await broker.handle(request(snapshot, "configuration_reference_validate"), f.host)).toMatchObject({ valid: false });
    vi.mocked(f.host.readWorkComplete).mockResolvedValue(true);
    await pending;
    expect(applied).toBe(true);
    expect(vi.mocked(f.host.retainLease).mock.results[0].value).toHaveBeenCalledOnce();
  });

  it("acknowledges an already released scope without unfreezing a different live scope", async () => {
    const f = await setup(), first = acquire();
    const old = await f.broker.handle(first, f.host) as ConfigurationReferenceSnapshot;
    await f.broker.handle(request(old, "configuration_reference_release"), f.host);
    const live = await f.broker.handle(acquire("b"), f.host) as ConfigurationReferenceSnapshot;
    vi.mocked(f.host.readWorkComplete).mockImplementation(async contextId => contextId === first.contextId);
    let applied = false;
    const pending = f.connection.reconcile(f.inventory).then(() => { applied = true; });
    await vi.waitFor(() => expect(f.host.ackWorkComplete).toHaveBeenCalledWith(first.contextId));
    expect(applied).toBe(false);
    expect(await f.broker.handle(request(live, "configuration_reference_validate", "b"), f.host)).toMatchObject({ valid: true });
    await f.broker.handle(request(live, "configuration_reference_release", "b"), f.host);
    await pending;
  });
});
