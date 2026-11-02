import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AssistantHost, type AssistantHostOptions, type AssistantHostRequest } from "../src/assistant/assistantHost.js";
import type { WorkbenchJobHandle, WorkbenchJobSpawnInput } from "../src/process/workbenchJob.js";
import type { ConfigurationReferenceHostContext } from "../src/assistant/configurationReferenceProtocol.js";
import { isConfigurationReferenceRequest, type ConfigurationReferenceSnapshot } from "../src/assistant/configurationReferenceProtocol.js";
import { ConfigurationReferenceLeaseBroker } from "../src/assistant/configurationReferenceLease.js";
import { AssistantProjectRegistryConnection } from "../src/assistant/projectRegistryConnection.js";
import type { MainControlRequest } from "../src/assistant/mainControlTransport.js";

const roots: string[] = [];
afterEach(() => { vi.unstubAllEnvs(); for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true, maxRetries: 10 }); });
function fixture(mainControl?: AssistantHostOptions["mainControl"], capability = true, hooks: Partial<AssistantHostOptions> = {}) {
  const root = mkdtempSync(join(tmpdir(), "assistant-control-host-")); roots.push(root);
  const python = join(root, "pythonw.exe"); writeFileSync(python, "never executed");
  const jobs = new Map<WorkbenchJobHandle, number>();
  let currentJob: WorkbenchJobHandle;
  const native = {
    spawn: vi.fn((input: WorkbenchJobSpawnInput) => {
      currentJob = {}; jobs.set(currentJob, 1);
      const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
      const instanceId = input.arguments[input.arguments.indexOf("--instance-id") + 1];
      writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant", instanceId, pid: 1234, port: 12345 }));
      return { pid: 1234, job: currentJob };
    }),
    terminate: vi.fn((job: WorkbenchJobHandle) => { jobs.set(job, 0); return true; }),
    activeCount: (job: WorkbenchJobHandle) => jobs.get(job) ?? 0,
    exitCode: (job: WorkbenchJobHandle) => jobs.get(job) === 0 ? 0 : null,
    drainStatus: () => ({ complete: true, channels: [] }), close: vi.fn((job: WorkbenchJobHandle) => jobs.delete(job)),
  };
  let claimed = false;
  const fetch = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/health")) return Response.json({ status: "ok", role: "launcher_assistant", protocolVersion: 1, ...(capability ? { mainControlVersion: 1 } : {}) });
    if (path.endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "synthetic-agent", directSessionId: "synthetic-session" } });
    if (path.endsWith("/next")) {
      if (!claimed) { claimed = true; return Response.json({ schemaVersion: 1, request: { deliveryId: "a".repeat(32), action: "project_lifecycle", projectId: "synthetic-project", operation: "start", requestId: "synthetic-request" } }); }
      return await new Promise<Response>((_resolve, reject) => {
        const abort = () => reject(new Error("aborted"));
        if (init?.signal?.aborted) abort(); else init?.signal?.addEventListener("abort", abort, { once: true });
      });
    }
    if (path.endsWith("/settle")) return Response.json({ schemaVersion: 1, accepted: true });
    if (path.endsWith("/shutdown")) { jobs.set(currentJob, 0); return Response.json({ stopping: true }); }
    return Response.json({ accepted: true });
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"), sourceRoot: root,
    pythonPath: python, projects: { "synthetic-project": root }, native, fetch, mainControl, ...hooks });
  return { host, native, fetch, root, currentJob: () => currentJob };
}

describe("AssistantHost private main control pump", () => {
  it.each([{ completeEarly: false, evicted: false }, { completeEarly: true, evicted: false }, { completeEarly: true, evicted: true }])(
    "keeps a lost release ACK safe and permits idle refresh despite an evicted metadata ACK (%j)", async ({ completeEarly, evicted }) => {
    const contextId = `cfg-${"e".repeat(32)}`, releaseDocument = vi.fn();
    const broker = new ConfigurationReferenceLeaseBroker({ acquireRegistryDocumentAdmission: async () => ({
      snapshot: { schemaVersion: 1, revision: 1, complete: true, projects: [] }, check: () => {}, release: releaseDocument,
    }) });
    const f = fixture(async (request, _signal, context) => isConfigurationReferenceRequest(request) ? broker.handle(request, context) : {}, true, {
      mainControlSettled: (request, value, accepted, context) => {
        if (isConfigurationReferenceRequest(request)) broker.settled(request, value, accepted, context);
      },
    });
    const baseFetch = f.fetch.getMockImplementation()!;
    let first = true, releaseDelivered = false, releaseLost = false, resumed = false, workComplete = completeEarly, acked = false;
    let snapshot!: ConfigurationReferenceSnapshot, ready!: () => void;
    const releaseReady = new Promise<void>(done => { ready = done; });
    const wait = (promise: Promise<void>, signal?: AbortSignal | null) => new Promise<void>((resolve, reject) => {
      const abort = () => { signal?.removeEventListener("abort", abort); reject(new Error("poll retired")); };
      if (signal?.aborted) abort(); else {
        signal?.addEventListener("abort", abort, { once: true });
        promise.then(() => { signal?.removeEventListener("abort", abort); resolve(); });
      }
    });
    const ackAttempts = vi.fn();
    f.fetch.mockImplementation(async (url, init) => {
      const path = String(url);
      if (path.endsWith("/main-control/next")) {
        if (first) { first = false; return Response.json({ schemaVersion: 1, request: {
          deliveryId: "e".repeat(32), action: "configuration_reference_acquire", contextId } }); }
        await wait(releaseReady, init?.signal);
        if (!releaseDelivered) {
          releaseDelivered = true;
          return Response.json({ schemaVersion: 1, request: { deliveryId: "f".repeat(32), action: "configuration_reference_release",
            contextId, leaseId: snapshot.leaseId, snapshotDigest: snapshot.snapshotDigest } });
        }
        if (releaseLost && !resumed) { resumed = true; return Response.json({ schemaVersion: 1, request: null }); }
        await wait(new Promise<void>(() => {}), init?.signal);
      }
      if (path.endsWith("/main-control/settle")) {
        const body = JSON.parse(String(init?.body));
        if (body.deliveryId === "e".repeat(32)) { snapshot = body.result; ready(); return Response.json({ schemaVersion: 1, accepted: true }); }
        releaseLost = true; throw new Error("release ACK lost");
      }
      if (path.endsWith(`/configuration-reference/contexts/${contextId}`)) {
        return Response.json({ schemaVersion: 1, contextId, known: !evicted, workComplete: !evicted && workComplete });
      }
      if (path.endsWith(`/configuration-reference/contexts/${contextId}/ack`)) {
        ackAttempts();
        acked = !evicted && workComplete;
        return Response.json({ schemaVersion: 1, contextId, acknowledged: acked });
      }
      if (path.endsWith("/migration-barrier/prepare")) return Response.json({ schemaVersion: 1, state: "probing" });
      if (path.endsWith("/migration-barrier/status")) return Response.json({ schemaVersion: 1, state: "ready" });
      return await baseFetch(url, init);
    });
    try {
      await f.host.start();
      await vi.waitFor(() => expect(releaseLost && resumed).toBe(true));
      await vi.waitFor(() => expect(ackAttempts).toHaveBeenCalled());
      expect(releaseDocument).toHaveBeenCalledOnce();
      if (!completeEarly) expect(acked).toBe(false);
      expect(f.native.terminate).not.toHaveBeenCalled(); expect(f.native.activeCount(f.currentJob())).toBe(1);
      if (evicted) {
        await vi.waitFor(() => expect(ackAttempts.mock.calls.length).toBeGreaterThanOrEqual(2));
        expect(acked).toBe(false);
        const admission = f.host.beginMigrationAdmission();
        try {
          await admission.seal();
          expect(await f.host.migrationBarrier("prepare")).toBe("probing");
          expect(await f.host.retireForMigration()).toBe(true);
          f.host.prepareForMigrationRestart({ schemaVersion: 1, revision: 0, projects: { "synthetic-project": f.root } }, false);
          await f.host.startForMigration();
          expect(f.host.snapshot().state).toBe("ready"); expect(f.native.spawn).toHaveBeenCalledTimes(2);
        } finally { admission.release(); }
      } else {
        workComplete = true;
        await vi.waitFor(() => expect(acked).toBe(true), { timeout: 3000 });
        expect(f.native.spawn).toHaveBeenCalledOnce();
      }
      expect(f.native.terminate).not.toHaveBeenCalled();
    } finally { await f.host.stop(); }
  });

  it.each([false, true])("recovers a lost configuration ACK under its scope proof without terminating an active Job (other unknown=%s)", async otherUnknown => {
    const contextId = `cfg-${"a".repeat(32)}`;
    const acquire: MainControlRequest = { deliveryId: "a".repeat(32), action: "configuration_reference_acquire", contextId };
    let broker!: ConfigurationReferenceLeaseBroker;
    let acquired: ConfigurationReferenceSnapshot | undefined;
    const settlements: Array<{ action: string; accepted: boolean | undefined; value: Record<string, unknown> }> = [];
    const f = fixture(async (request, _signal, context) => isConfigurationReferenceRequest(request) ? broker.handle(request, context) : {}, true, {
      mainControlSettled: (request, value, accepted, context) => {
        settlements.push({ action: request.action, accepted, value });
        if (isConfigurationReferenceRequest(request)) {
          if (request.action === "configuration_reference_acquire") acquired = value as ConfigurationReferenceSnapshot;
          broker.settled(request, value, accepted, context);
        }
      },
    });
    const connection = new AssistantProjectRegistryConnection(join(f.root, "reference-registry.json"));
    const inventory = { schemaVersion: 1, integrationRoot: f.root, items: [{ id: "main", path: f.root, checkedOut: true }] };
    await connection.reconcile(inventory);
    broker = new ConfigurationReferenceLeaseBroker(connection);
    const queued: MainControlRequest[] = [acquire];
    const waiting: Array<(request: MainControlRequest) => void> = [];
    const offer = (request: MainControlRequest) => { const next = waiting.shift(); if (next) next(request); else queued.push(request); };
    const baseFetch = f.fetch.getMockImplementation()!;
    let proof: Record<string, unknown> = { schemaVersion: 1, contextId, known: false, workComplete: false };
    const proofReads: Array<Record<string, unknown>> = [], acknowledged: string[] = [];
    f.fetch.mockImplementation(async (url, init) => {
      const path = String(url);
      if (path.endsWith("/main-control/next")) {
        const request = queued.shift();
        if (request) return Response.json({ schemaVersion: 1, request });
        return await new Promise<Response>((resolve, reject) => {
          const deliver = (next: MainControlRequest) => { init?.signal?.removeEventListener("abort", abort); resolve(Response.json({ schemaVersion: 1, request: next })); };
          const abort = () => { const index = waiting.indexOf(deliver); if (index >= 0) waiting.splice(index, 1); reject(new Error("poll retired")); };
          if (init?.signal?.aborted) abort(); else { waiting.push(deliver); init?.signal?.addEventListener("abort", abort, { once: true }); }
        });
      }
      if (path.endsWith("/main-control/settle")) {
        const body = JSON.parse(String(init?.body)) as { deliveryId: string };
        if (body.deliveryId === acquire.deliveryId || body.deliveryId === "c".repeat(32)) throw new Error("settle ACK was lost");
        return Response.json({ schemaVersion: 1, accepted: true });
      }
      if (path.endsWith(`/configuration-reference/contexts/${contextId}`)) {
        proofReads.push({ ...proof }); return Response.json(proof);
      }
      if (path.endsWith(`/configuration-reference/contexts/${contextId}/ack`)) {
        expect(JSON.parse(String(init?.body))).toEqual({ schemaVersion: 1 });
        acknowledged.push(contextId); return Response.json({ schemaVersion: 1, contextId, acknowledged: true });
      }
      return await baseFetch(url, init);
    });
    let applied = false, registryWrite: Promise<unknown> | undefined;
    try {
      await f.host.start();
      await vi.waitFor(() => expect(settlements.some(row => row.action === "configuration_reference_acquire" && row.accepted === undefined)).toBe(true));
      expect(acquired?.complete).toBe(true);
      registryWrite = connection.reconcile(inventory).then(value => { applied = true; return value; });
      await vi.waitFor(() => expect(proofReads.length).toBeGreaterThan(0));
      expect(applied).toBe(false);
      expect(f.native.terminate).not.toHaveBeenCalled(); expect(f.native.close).not.toHaveBeenCalled();
      expect(f.native.activeCount(f.currentJob())).toBe(1);
      await expect(f.host.request({ operation: "status" })).resolves.toMatchObject({ assistant: { directSessionId: "synthetic-session" } });
      offer({ deliveryId: "b".repeat(32), action: "configuration_reference_validate", contextId,
        leaseId: acquired!.leaseId, snapshotDigest: acquired!.snapshotDigest });
      await vi.waitFor(() => expect(settlements.some(row => row.action === "configuration_reference_validate" && row.value.valid === false)).toBe(true));
      if (otherUnknown) {
        offer({ deliveryId: "c".repeat(32), action: "project_lifecycle", projectId: "synthetic-project", operation: "start", requestId: "other-original" });
        await vi.waitFor(() => expect(settlements.some(row => row.action === "project_lifecycle" && row.accepted === undefined)).toBe(true));
      }
      proof = { schemaVersion: 1, contextId: `cfg-${"f".repeat(32)}`, known: true, workComplete: true };
      await vi.waitFor(() => expect(proofReads.some(row => row.contextId !== contextId)).toBe(true), { timeout: 3000 });
      expect(applied).toBe(false); expect(acknowledged).toEqual([]);
      proof = { schemaVersion: 1, contextId, known: false, workComplete: true }; // Incoherent proof is also rejected.
      await vi.waitFor(() => expect(proofReads.some(row => row.known === false && row.workComplete === true)).toBe(true), { timeout: 3000 });
      expect(applied).toBe(false);
      // Only the native worker's eventual finally proof changes; no renderer
      // request, restart, Job exit, or remote-task cancellation is required.
      proof = { schemaVersion: 1, contextId, known: true, workComplete: true };
      await vi.waitFor(() => expect(applied).toBe(true), { timeout: 3000 });
      await registryWrite;
      await vi.waitFor(() => expect(acknowledged).toContain(contextId));
      expect(f.native.activeCount(f.currentJob())).toBe(1);
      expect(f.native.spawn).toHaveBeenCalledOnce(); expect(f.native.terminate).not.toHaveBeenCalled();
      expect(settlements.filter(row => row.action === "configuration_reference_acquire")).toHaveLength(1);
      if (otherUnknown) expect(() => f.host.beginMigrationAdmission()).toThrow("ASSISTANT_MIGRATION_BUSY");
      else f.host.beginMigrationAdmission().release();
      offer({ deliveryId: "d".repeat(32), action: "configuration_reference_release", contextId,
        leaseId: acquired!.leaseId, snapshotDigest: acquired!.snapshotDigest });
      await vi.waitFor(() => expect(settlements.some(row => row.action === "configuration_reference_release" && row.value.released === true)).toBe(true));
    } finally {
      await f.host.stop();
      await registryWrite;
    }
  });

  it("binds private authority to the captured native generation and waits for real exit and output drain", async () => {
    let context: ConfigurationReferenceHostContext | undefined;
    const f = fixture(async (_request, _signal, hostContext) => { context = hostContext; return {}; });
    let outputDrained = false;
    f.native.drainStatus = () => ({ complete: outputDrained, channels: [] });
    await f.host.start();
    await vi.waitFor(() => expect(context).toBeDefined());
    expect(context!.agentId).toBe("synthetic-agent"); expect(context!.sessionId).toBe("synthetic-session");
    expect(context!.nativeAssistantRoot).toContain("profile"); context!.check();
    let released = false;
    const drain = context!.drain().then(() => { released = true; });
    const stopping = f.host.stop();
    await vi.waitFor(() => expect(context!.signal.aborted).toBe(true));
    expect(() => context!.check()).toThrow("ASSISTANT_NOT_READY");
    expect(released).toBe(false);
    outputDrained = true;
    await stopping; await drain; expect(released).toBe(true);
    await f.host.start();
    expect(() => context!.check()).toThrow("ASSISTANT_NOT_READY");
    await expect(f.host.request({ operation: "configuration_reference_acquire", contextId: `cfg-${"a".repeat(32)}` } as unknown as AssistantHostRequest))
      .rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    await f.host.stop();
  });

  it("keeps the host alive when the control pump fails during a migration fence", async () => {
    const f = fixture(vi.fn(async () => ({})));
    const original = f.fetch.getMockImplementation()!;
    let fail!: (error: Error) => void;
    f.fetch.mockImplementation(async (url, init) => String(url).endsWith("/main-control/next")
      ? await new Promise<Response>((_done, reject) => { fail = reject; }) : await original(url, init));
    await f.host.start();
    await vi.waitFor(() => expect(fail).toBeTypeOf("function"));
    const fence = f.host.beginMigrationAdmission();
    await fence.seal();
    fail(new Error("lost control channel"));
    await vi.waitFor(async () => await expect(f.host.migrationBarrier("prepare")).rejects.toThrow("ASSISTANT_NOT_READY"));
    expect(f.native.terminate).not.toHaveBeenCalled();
    expect(f.native.close).not.toHaveBeenCalled();
    fence.release();
    expect(() => f.host.beginMigrationAdmission()).toThrow("ASSISTANT_MIGRATION_BUSY");
    await f.host.stop();
  });

  it("waits for the actual admitted delivery before migration admission drains", async () => {
    let finish!: () => void;
    const mainControl = vi.fn(async () => { await new Promise<void>(done => { finish = done; }); return {}; });
    const f = fixture(mainControl);
    await f.host.start();
    await vi.waitFor(() => expect(finish).toBeTypeOf("function"));
    const fence = f.host.beginMigrationAdmission();
    let drained = false;
    void fence.drained.then(() => { drained = true; });
    await Promise.resolve();
    expect(drained).toBe(false);
    finish();
    await fence.drained;
    expect(drained).toBe(true);
    fence.release();
    await f.host.stop();
  });

  it("starts only a negotiated private capability and never exposes it to renderer requests", async () => {
    const mainControl = vi.fn(async () => ({ schemaVersion: 1, projectId: "synthetic-project", operation: "start", requestId: "synthetic-request", state: "unknown", code: "receipt_unavailable" }));
    const f = fixture(mainControl);
    try {
      await f.host.start();
      await vi.waitFor(() => expect(f.fetch.mock.calls.some(([url]) => String(url).endsWith("/settle"))).toBe(true));
      expect(mainControl).toHaveBeenCalledTimes(1);
      expect(f.native.spawn.mock.calls[0][0].env.VIBELUTION_ASSISTANT_MAIN_CONTROL).toBe("1");
      const settle = f.fetch.mock.calls.find(([url]) => String(url).endsWith("/settle"))!;
      const headers = settle[1]!.headers as Record<string, string>;
      expect(typeof headers.Authorization === "string" && headers.Authorization.startsWith("Bearer ")).toBe(true);
      await expect(f.host.request({ operation: "project_lifecycle", projectId: "synthetic-project" } as unknown as AssistantHostRequest)).rejects.toThrow("ASSISTANT_REQUEST_INVALID");
    } finally { await f.host.stop(); }
  });

  it("does not inherit a control flag when no main owner exists", async () => {
    vi.stubEnv("VIBELUTION_ASSISTANT_MAIN_CONTROL", "1");
    const f = fixture();
    try {
      await f.host.start();
      expect(f.native.spawn.mock.calls[0][0].env.VIBELUTION_ASSISTANT_MAIN_CONTROL).toBeUndefined();
      expect(f.fetch.mock.calls.some(([url]) => String(url).includes("main-control"))).toBe(false);
    } finally { await f.host.stop(); }
  });

  it("refuses an incompatible child capability before delivering a main operation", async () => {
    const mainControl = vi.fn();
    const f = fixture(mainControl, false);
    await expect(f.host.start()).rejects.toThrow("ASSISTANT_MAIN_CONTROL_UNAVAILABLE");
    expect(mainControl).not.toHaveBeenCalled();
    expect(f.native.close).toHaveBeenCalledTimes(1);
  });

  it("does not cancel an admitted project command or send its late result into a restarted host", async () => {
    let release!: () => void;
    const gate = new Promise<void>(resolve => { release = resolve; });
    let completed = false;
    const mainControl = vi.fn(async () => { await gate; completed = true; return {}; });
    const f = fixture(mainControl);
    await f.host.start();
    await vi.waitFor(() => expect(mainControl).toHaveBeenCalledTimes(1));
    await f.host.stop(); await f.host.start();
    release(); await vi.waitFor(() => expect(completed).toBe(true));
    expect(f.fetch.mock.calls.some(([url]) => String(url).endsWith("/settle"))).toBe(false);
    await f.host.stop();
  });
});
