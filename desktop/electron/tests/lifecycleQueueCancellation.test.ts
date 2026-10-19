import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";
import { LauncherLifecycleSupervisor } from "../src/lifecycle/launcherLifecycleSupervisor.js";
import { createMainLineCommandQueue, type MainLineLifecycleResult } from "../src/lifecycle/mainLine/commandQueue.js";
import { executeMainLineWorkbench, reclaimStaleWorkbenchBackend } from "../src/process/workbenchBackend.js";
import { runWorkbenchLifecycle } from "../src/process/workbenchLifecycle.js";
import { __setWorkbenchJobNativeForTests, hasTrackedWorkbenchJob, spawnTrackedWorkbenchProcess, terminateTrackedWorkbenchJob } from "../src/process/workbenchJob.js";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

const ok = (operation: string): MainLineLifecycleResult => ({ schemaVersion: 1, accepted: true, operation });
const superseded = () => new Error("launcher lifecycle intent superseded for main");
const flush = async () => { for (let index = 0; index < 12; index += 1) await Promise.resolve(); };

describe("cancelled lifecycle queue ownership", () => {
  it("enters close before a superseded mutation finishes and keeps its successor lane", async () => {
    const supervisor = new LauncherLifecycleSupervisor();
    const blocked = deferred<string>();
    const start = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
    const old = supervisor.executeMutation({ lease: start, mutate: () => blocked.promise, reconcile: vi.fn() });
    await flush();
    const close = supervisor.beginIntent({ instanceId: "main", operation: "close", desiredState: "closed" });
    const closeGate = deferred<string>();
    const mutate = vi.fn(() => closeGate.promise);
    const closing = supervisor.executeMutation({ lease: close, mutate, reconcile: vi.fn() });
    await flush();
    expect(mutate).toHaveBeenCalledOnce();
    blocked.resolve("old");
    await expect(old).resolves.toMatchObject({ outcome: "superseded" });
    expect(supervisor.isCurrent(close)).toBe(true);
    // Another call using the current lease must still wait for that lease's
    // active mutation even though the detached predecessor has now settled.
    const sameLeaseMutate = vi.fn(async () => "same");
    const sameLease = supervisor.executeMutation({ lease: close, mutate: sameLeaseMutate, reconcile: vi.fn() });
    await flush();
    expect(sameLeaseMutate).not.toHaveBeenCalled();
    closeGate.resolve("closed");
    await expect(closing).resolves.toMatchObject({ outcome: "committed" });
    await expect(sameLease).resolves.toMatchObject({ outcome: "committed" });
  });

  it.each(["resolve", "reject"] as const)("ignores a cancelled close's late %s for active state and retry backoff", async (settlement) => {
    const queue = createMainLineCommandQueue();
    const controller = new AbortController();
    const oldGate = deferred<MainLineLifecycleResult>();
    const old = queue.submit({ operation: "stop", signal: controller.signal, execute: () => oldGate.promise });
    const rejected = expect(old).rejects.toThrow("superseded");
    controller.abort(superseded());
    await rejected;
    const newGate = deferred<MainLineLifecycleResult>();
    const start = queue.submit({ operation: "start", execute: () => newGate.promise });
    const startId = queue.snapshot().active?.commandId;
    if (settlement === "resolve") oldGate.resolve(ok("stop"));
    else oldGate.reject(new Error("old failure"));
    await flush();
    expect(queue.snapshot().active?.commandId).toBe(startId);
    newGate.resolve(ok("start"));
    await start;
    await flush();
    const executeClose = vi.fn(async () => ok("stop"));
    const closed = await queue.submit({ operation: "stop", execute: executeClose });
    expect(executeClose).toHaveBeenCalledOnce();
    expect(closed.code).toBeUndefined();
  });

  it("does not join a new start to a detached start, or execute cancelled pending work", async () => {
    const queue = createMainLineCommandQueue();
    const controller = new AbortController();
    const oldGate = deferred<MainLineLifecycleResult>();
    const old = queue.submit({ operation: "start", signal: controller.signal, execute: () => oldGate.promise });
    const rejected = expect(old).rejects.toThrow("superseded");
    controller.abort(superseded());
    await rejected;
    const closeGate = deferred<MainLineLifecycleResult>();
    const close = queue.submit({ operation: "force-stop", execute: () => closeGate.promise });
    const pendingController = new AbortController();
    const neverExecute = vi.fn();
    const pending = queue.submit({ operation: "start", signal: pendingController.signal, execute: neverExecute });
    const pendingRejected = expect(pending).rejects.toThrow("superseded");
    pendingController.abort(superseded());
    await pendingRejected;
    const executeStart = vi.fn(async () => ok("start"));
    const start = queue.submit({ operation: "start", execute: executeStart });
    oldGate.resolve(ok("start"));
    await flush();
    expect(queue.snapshot().active?.operation).toBe("force-stop");
    closeGate.resolve(ok("force-stop"));
    await close;
    await expect(start).resolves.toMatchObject({ accepted: true });
    expect(executeStart).toHaveBeenCalledOnce();
    expect(neverExecute).not.toHaveBeenCalled();
  });

  it("keeps the latest persisted intent after an older asynchronous write settles", async () => {
    const disk = deferred<void>();
    const written: string[] = [];
    const persist = vi.fn(async (intent: { operation: string }) => {
      if (intent.operation === "start") await disk.promise;
      written.push(intent.operation);
    });
    const queue = createMainLineCommandQueue({ persistIntent: persist });
    await queue.submit({ operation: "start", execute: async () => ok("start") });
    await queue.submit({ operation: "force-stop", execute: async () => ok("force-stop") });
    disk.resolve();
    await flush();
    expect(written.at(-1)).toBe("force-stop");
  });

  it("does not reuse an older close after an admitted start is cancelled before settlement", async () => {
    const queue = createMainLineCommandQueue();
    await queue.submit({ operation: "stop", execute: async () => ok("stop") });
    const controller = new AbortController();
    const oldGate = deferred<MainLineLifecycleResult>();
    const start = queue.submit({ operation: "start", signal: controller.signal, execute: () => oldGate.promise });
    const rejected = expect(start).rejects.toThrow("superseded");
    controller.abort(superseded());
    await rejected;
    const executeClose = vi.fn(async () => ok("stop"));
    const close = await queue.submit({ operation: "stop", execute: executeClose });
    expect(executeClose).toHaveBeenCalledOnce();
    expect(close.code).toBeUndefined();
    oldGate.resolve(ok("start"));
    await flush();
  });
});

describe("late lifecycle work fences", () => {
  function harness() {
    const root = mkdtempSync(join(tmpdir(), "vibelution-lifecycle-fence-"));
    const spawnImpl = vi.fn(() => ({ pid: 4242, exitCode: null, killed: false, unref: () => undefined, kill: () => true }));
    const writeState = vi.fn();
    return {
      root, spawnImpl, writeState,
      input: {
        workspaceRoot: root, pythonPath: "python", operation: "start" as const,
        command: { commandId: "old", type: "open" as const, operation: "start" as const, noBrowser: true },
        spawnImpl, writeState, readState: () => ({ backendPort: 8000 }),
        readDaemonPid: () => 0, readDaemonIdentity: () => null,
        ensureFrontend: async () => undefined, connect: async () => false, pidAlive: () => false,
        killPid: vi.fn(), captureProcessIdentity: async ({ pid }: { pid: number }) => ({ pid, createTime: 1, executable: "python" })
      }
    };
  }

  it.each(["frontend", "port"])("does not spawn or persist when superseded during an uncooperative %s await", async (stage) => {
    const { root, input, spawnImpl, writeState } = harness();
    const gate = deferred<void>();
    const entered = deferred<void>();
    const controller = new AbortController();
    let probes = 0;
    try {
      const start = executeMainLineWorkbench({
        ...input, signal: controller.signal,
        ensureFrontend: async () => { if (stage === "frontend") { entered.resolve(); await gate.promise; } },
        connect: async () => { if (stage === "port" && ++probes === 2) { entered.resolve(); await gate.promise; } return false; }
      });
      const rejected = expect(start).rejects.toThrow("superseded");
      await entered.promise;
      controller.abort(superseded());
      gate.resolve();
      await rejected;
      expect(spawnImpl).not.toHaveBeenCalled();
      expect(writeState).not.toHaveBeenCalled();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });

  it("runs a close through both lanes while the cancelled frontend still waits", async () => {
    const { root, input, spawnImpl, writeState } = harness();
    const queue = createMainLineCommandQueue();
    const supervisor = new LauncherLifecycleSupervisor();
    const gate = deferred<void>();
    const entered = deferred<void>();
    try {
      const lease = supervisor.beginIntent({ instanceId: "main", operation: "start", desiredState: "open" });
      const start = supervisor.executeMutation({ lease, reconcile: vi.fn(), mutate: () => runWorkbenchLifecycle({
        ...input, operatorConfigPath: "unused", queue, signal: lease.signal,
        ensureFrontend: async () => { entered.resolve(); await gate.promise; }
      }) });
      await entered.promise;
      const close = supervisor.beginIntent({ instanceId: "main", operation: "force-stop", desiredState: "closed" });
      const closing = supervisor.executeMutation({ lease: close, reconcile: vi.fn(), mutate: () => runWorkbenchLifecycle({
        ...input, operatorConfigPath: "unused", operation: "force-stop", queue, signal: close.signal
      }) });
      await expect(closing).resolves.toMatchObject({ outcome: "committed", value: { accepted: true } });
      const writesAfterClose = writeState.mock.calls.length;
      expect(writesAfterClose).toBe(1);
      gate.resolve();
      await start;
      await flush();
      expect(writeState).toHaveBeenCalledTimes(writesAfterClose);
      expect(spawnImpl).not.toHaveBeenCalled();
    } finally { rmSync(root, { recursive: true, force: true }); }
  });

  it("does not retire a replacement Job after an old graceful request returns", async () => {
    const { root } = harness();
    const controller = new AbortController();
    const gate = deferred<{ completed: boolean; requested: boolean; status: number; reason: string }>();
    const entered = deferred<void>();
    const terminate = vi.fn(() => true);
    __setWorkbenchJobNativeForTests({
      spawn: () => ({ pid: 4243, job: {} }), terminate,
      activeCount: () => 1, close: vi.fn(), drainStatus: () => ({ complete: false, channels: [] })
    });
    try {
      const reclaim = reclaimStaleWorkbenchBackend({
        workspaceRoot: root, port: 8000, signal: controller.signal,
        connect: async () => true, pidAlive: () => true,
        fetchHealth: async () => ({ status: 200, json: async () => ({ status: "ok", routesReady: true, workspaceRoot: root, pid: 4242 }) }),
        gracefulShutdown: async () => { entered.resolve(); return await gate.promise; }
      });
      const rejected = expect(reclaim).rejects.toThrow("superseded");
      await entered.promise;
      controller.abort(superseded());
      spawnTrackedWorkbenchProcess(root, { executable: "python", arguments: [], cwd: root, env: {}, stdoutPath: "out", stderrPath: "err" });
      gate.resolve({ completed: true, requested: true, status: 202, reason: "old done" });
      await rejected;
      expect(terminate).not.toHaveBeenCalled();
      expect(hasTrackedWorkbenchJob(root)).toBe(true);
    } finally {
      __setWorkbenchJobNativeForTests(undefined);
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("keeps a replacement Job when a cancelled startup's identity capture returns late", async () => {
    const { root, input, writeState } = harness();
    const controller = new AbortController();
    const entered = deferred<void>();
    const identity = deferred<{ pid: number; createTime: number; executable: string }>();
    const jobs = new Map<object, number>();
    const terminate = vi.fn((job: object) => { jobs.set(job, 0); return true; });
    __setWorkbenchJobNativeForTests({
      spawn: () => { const job = {}; jobs.set(job, 1); return { pid: 4242, job }; },
      terminate, activeCount: (job) => jobs.get(job) ?? 0, close: vi.fn(),
      drainStatus: (job) => ({ complete: jobs.get(job) === 0, channels: [] })
    });
    const spawnOwned = () => spawnTrackedWorkbenchProcess(root, {
      executable: "python", arguments: [], cwd: root, env: {}, stdoutPath: "out", stderrPath: "err"
    });
    try {
      const start = executeMainLineWorkbench({
        ...input, signal: controller.signal,
        spawnImpl: () => { spawnOwned(); return { pid: 4242, exitCode: null, killed: false, unref: () => undefined, kill: () => true }; },
        captureProcessIdentity: async () => { entered.resolve(); return await identity.promise; }
      });
      const rejected = expect(start).rejects.toThrow("superseded");
      await entered.promise;
      controller.abort(superseded());
      expect(await terminateTrackedWorkbenchJob(root, 4242)).toBe(true);
      spawnOwned();
      identity.resolve({ pid: 4242, createTime: 1, executable: "python" });
      await rejected;
      expect(terminate).toHaveBeenCalledOnce();
      expect(hasTrackedWorkbenchJob(root)).toBe(true);
      expect(input.killPid).not.toHaveBeenCalled();
      expect(writeState).not.toHaveBeenCalled();
    } finally {
      __setWorkbenchJobNativeForTests(undefined);
      rmSync(root, { recursive: true, force: true });
    }
  });
});
