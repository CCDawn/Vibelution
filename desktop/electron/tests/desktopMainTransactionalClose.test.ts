import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MainWorkbenchCloseTransactionStore, isWorkbenchStartBlockedByClose, type MainWorkbenchCloseTransaction } from "../src/lifecycle/workbenchCloseTransactionStore.js";
import { createDesktopShellExitDeadline, withDesktopShellExitTimeout } from "../src/shutdown/desktopShellExit.js";
import { isActiveWorkProbeAuthFailure, resolveQuitActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";
import { isWorkbenchCloseControlFetchFailure } from "../src/lifecycle/workbenchCloseFailOpen.js";
import type { WorkbenchCloseTiming } from "../src/process/fastWorkbenchClose.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));
const closeStoreSource = readFileSync(
  fileURLToPath(new URL("../src/lifecycle/workbenchCloseTransactionStore.ts", import.meta.url)),
  "utf8",
);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

async function flushCloseCallbacks() {
  for (let step = 0; step < 20; step += 1) await Promise.resolve();
}

const releaseCloseHarnesses: Array<() => Promise<void>> = [];

function closeHarness(options: { platform?: string; owner?: boolean } = {}) {
  const source = readFileSync(mainSourcePath, "utf8");
  const begin = source.indexOf("async function requestTransactionalWorkbenchClose(");
  const end = source.indexOf("\nasync function stopWorkbenchBackend(", begin);
  const context = vi.fn(async (_bootstrap: unknown, options: { forceControlTokenRefresh?: boolean; signal?: AbortSignal } = {}) => ({
    launcherOrigin: "http://127.0.0.1:1234", controlToken: options.forceControlTokenRefresh ? "fresh" : "cached", desktopSessionId: "stable-session"
  }));
  const probe = vi.fn(async (_input: { controlToken: string; signal?: AbortSignal }) => ({ state: "idle", message: "" }));
  const confirm = vi.fn(async () => false);
  const stop = vi.fn(async (_paths: object, _bootstrap: object, _transaction: MainWorkbenchCloseTransaction, _signal: AbortSignal, _timing?: WorkbenchCloseTiming) => undefined);
  const closed = vi.fn(async (_options?: { deadlineAt?: number }): Promise<{ open: boolean } | undefined> => undefined);
  const closeInFlight = vi.fn(() => false);
  const record = vi.fn();
  const store = new MainWorkbenchCloseTransactionStore();
  const coordinator = vi.fn(async (_reason: string, run: () => Promise<void>) => run());
  const readStatus = vi.fn(async (_workspaceRoot: string) => ({ observedState: "closed" }));
  const readback = vi.fn(async (input: { readStatus: () => Promise<unknown>; timeoutMs: number; signal?: AbortSignal }) => {
    const status = await input.readStatus() as { observedState: string };
    return status.observedState === "closed";
  });
  const retireBuilds = vi.fn(async () => true);
  const captureBuilds = vi.fn(() => retireBuilds);
  const backend = deferred<"closed" | "superseded">();
  const getOwner = vi.fn((_root: string) => options.owner === false ? undefined : { status: "pending", completion: backend.promise });
  let retirementPending = false;
  const markPending = vi.fn((_epoch: number) => { retirementPending = true; return true; });
  const isCurrent = vi.fn((_epoch: number) => true);
  const releasePending = vi.fn((_epoch: number) => { retirementPending = false; });
  const commitClosed = vi.fn((epoch: number) => {
    if (!isCurrent(epoch)) return false;
    retirementPending = false;
    return true;
  });
  const beginLifecycle = vi.fn(() => 1);
  const canarySummary = vi.fn();
  const notify = vi.fn();
  const sandbox: Record<string, unknown> = {
    AbortSignal, Date, Error, performance, setTimeout, clearTimeout, randomUUID: () => "explicit-close-request",
    process: { platform: options.platform ?? "win32" }, WORKBENCH_CLOSE_BACKEND_WAIT_MS: 1800, WORKBENCH_CLOSE_FORCE_AFTER_MS: 1200,
    WORKBENCH_CLOSE_TOTAL_WAIT_MS: 2000,
    windowProvider: { approveWorkbenchCloseOnce: closed, isWorkbenchCloseInFlight: closeInFlight },
    desktopLifecycleCoordinator: { request: coordinator },
    resolveDesktopActionLoopContext: context,
    currentDesktopSessionId: () => "stable-session", desktopEnvironment: () => ({}),
    fetchLauncherActiveWorkStatus: probe,
    resolveQuitActiveWorkStatus, isActiveWorkProbeAuthFailure,
    isWorkbenchCloseControlFetchFailure,
    createDesktopShellExitDeadline, withDesktopShellExitTimeout,
    captureFrontendBuildRetirement: captureBuilds,
    getBackgroundWorkbenchRetirement: getOwner,
    mainWorkbenchCloseStore: store,
    launcherStateStore: { beginMainLifecycle: beginLifecycle, markMainRetirementPending: markPending,
      isMainLifecycleCurrent: isCurrent, releaseMainRetirementPending: releasePending, commitVerifiedMainClosed: commitClosed },
    confirmWorkbenchForceClose: confirm,
    notifyDesktopTray: notify,
    recordSupervisorEventFallbackLocally: record,
    stopWorkbenchBackend: stop,
    waitForWorkbenchBackendSettledForWindowClose: readback,
    readRuntimeManagerLauncherStatusSummary: readStatus,
    desktopControlContextForLocalClose: () => ({ desktopSessionId: "stable-session", controlToken: "cached" }),
    writeWorkbenchCloseCanarySummary: canarySummary,
    desktopSessionRevision: 1,
    shutdownApproved: false,
    pendingWorkbenchCloseAck: null, workbenchCloseBackendStopInFlight: null, workbenchFailedCloseHandling: false, workbenchCloseGeneration: 0,
    workbenchOpenControllers: new Set<AbortController>()
  };
  const ackBegin = source.indexOf("async function acknowledgeTransactionalWorkbenchClose(");
  const ackEnd = source.indexOf("\nfunction writeWorkbenchCloseCanarySummary(", ackBegin);
  runInNewContext(transpileModule(source.slice(begin, end) + source.slice(ackBegin, ackEnd)
    + "\nglobalThis.runClose = requestTransactionalWorkbenchClose; globalThis.ackClose = acknowledgeTransactionalWorkbenchClose;", {
    compilerOptions: { target: ScriptTarget.ES2022 }
  }).outputText, sandbox);
  releaseCloseHarnesses.push(async () => {
    isCurrent.mockReturnValue(false);
    backend.resolve("superseded");
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(1250);
    await flushCloseCallbacks();
    expect(sandbox.workbenchCloseBackendStopInFlight).toBeNull();
  });
  return { context, probe, confirm, stop, closed, record, store, coordinator, readback, readStatus, retireBuilds, captureBuilds,
    commitClosed, beginLifecycle, markPending, isCurrent, releasePending, getOwner, backend, canarySummary, notify, closeInFlight,
    pending: () => retirementPending,
    pendingAck: () => sandbox.pendingWorkbenchCloseAck,
    acknowledge: () => (sandbox.ackClose as (paths: object, bootstrap: object) => Promise<void>)({ workspaceRoot: "test-workspace" }, {}),
    run: () => (sandbox.runClose as (paths: object, bootstrap: object) => Promise<void>)({ workspaceRoot: "test-workspace" }, {}) };
}

afterEach(async () => {
  try {
    for (const release of releaseCloseHarnesses.splice(0)) await release();
    if (vi.isFakeTimers()) expect(vi.getTimerCount()).toBe(0);
  } finally {
    vi.useRealTimers();
  }
});

describe("Explicit Workbench close", () => {
  it("interrupts work without waiting for a status probe, control token, or confirmation", async () => {
    const h = closeHarness();
    h.context.mockImplementation(() => new Promise(() => undefined));
    h.probe.mockImplementation(() => new Promise(() => undefined));
    await h.run();
    expect(h.context).not.toHaveBeenCalled();
    expect(h.probe).not.toHaveBeenCalled();
    expect(h.confirm).not.toHaveBeenCalled();
    expect(h.stop).toHaveBeenCalledOnce();
    expect(h.stop.mock.calls[0][2]).toMatchObject({
      mode: "force", reason: "workbench_window_close", activeWorkState: "unknown", requestId: "explicit-close-request"
    });
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.markPending).toHaveBeenCalledWith(1);
    expect(h.stop.mock.invocationCallOrder[0]).toBeLessThan(h.markPending.mock.invocationCallOrder[0]!);
    expect(h.markPending.mock.invocationCallOrder[0]).toBeLessThan(h.closed.mock.invocationCallOrder[0]!);
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
  });

  it("passes one absolute request deadline and force time through the fifth stop argument", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    const requestedAt = Date.now();
    h.coordinator.mockImplementation(async (_reason, run) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await run();
    });
    h.stop.mockImplementation(async () => {
      await new Promise((resolve) => setTimeout(resolve, 400));
    });
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(900);
    await closing;
    expect(h.stop.mock.calls[0][4]).toEqual({
      deadlineAt: requestedAt + 1800, forceAt: requestedAt + 1200,
      background: { retireFrontendBuilds: h.retireBuilds }
    });
    expect(h.readback).not.toHaveBeenCalled();
    expect(h.closed).toHaveBeenCalledWith({ deadlineAt: requestedAt + 2000 });
  });

  it("keeps window-first acknowledgement pending until the owned backend confirms closed", async () => {
    const h = closeHarness();
    await h.run();
    await h.acknowledge();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "background_closing", windowAcknowledged: true });
    expect(h.pending()).toBe(true);
    expect(h.pendingAck()).toMatchObject({ projectionEpoch: 1 });
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.canarySummary).not.toHaveBeenCalled();
    expect(h.notify).toHaveBeenCalledWith("Vibelution", "工作台窗口已关闭，后台仍在回收。可在 Launcher 查看“停止中”状态。");
    await h.acknowledge();
    expect(h.notify).toHaveBeenCalledTimes(1);

    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.commitClosed).toHaveBeenCalledExactlyOnceWith(1);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.pending()).toBe(false);
    expect(h.pendingAck()).toBeNull();
    expect(h.canarySummary).toHaveBeenCalledOnce();
    expect(h.record).toHaveBeenCalledWith(expect.objectContaining({ eventCode: "electron.workbench_close.completed" }));
  });

  it("keeps backend-first completion awaiting the actual window acknowledgement", async () => {
    const h = closeHarness();
    await h.run();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.pending()).toBe(true);
    expect(h.pendingAck()).toMatchObject({ projectionEpoch: 1 });
    expect(h.store.currentTransaction()?.phase).toBe("window_close_authorized");
    expect(h.canarySummary).not.toHaveBeenCalled();
    await h.acknowledge();
    expect(h.commitClosed).toHaveBeenCalledExactlyOnceWith(1);
    expect(h.pending()).toBe(false);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.pendingAck()).toBeNull();
    expect(h.canarySummary).toHaveBeenCalledOnce();
  });

  it("closes promptly while a stalled background owner stays pending beyond the admission deadline", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    const requestedAt = Date.now();
    await h.run();
    expect(h.closed).toHaveBeenCalledOnce();
    expect(Date.now()).toBe(requestedAt);
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.pending()).toBe(true);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.canarySummary).not.toHaveBeenCalled();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
  });

  it("does not authorize window close when backend stopping fails", async () => {
    const h = closeHarness();
    h.stop.mockRejectedValueOnce(new Error("owned process still running"));
    await expect(h.run()).rejects.toThrow("owned process still running");
    expect(h.readback).not.toHaveBeenCalled();
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.markPending).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "backend_stop_admission_failed" });
  });

  it("keeps a newer start's window when admission loses its projection epoch", async () => {
    const h = closeHarness();
    h.markPending.mockReturnValueOnce(false);
    await h.run();
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.getOwner).not.toHaveBeenCalled();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.pendingAck()).toBeNull();
  });

  it.each(["owner", "projection"])("does not claim closed when the background %s epoch is superseded", async (stage) => {
    const h = closeHarness();
    await h.run();
    await h.acknowledge();
    if (stage === "projection") h.isCurrent.mockReturnValue(false);
    h.backend.resolve(stage === "owner" ? "superseded" : "closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.pendingAck()).toBeNull();
    expect(h.canarySummary).not.toHaveBeenCalled();
    expect(h.pending()).toBe(stage !== "owner");
    expect(h.record.mock.calls.some(([event]) => event.eventCode === "electron.workbench_close.completed")).toBe(false);
    if (stage === "owner") {
      expect(h.commitClosed).not.toHaveBeenCalled();
      expect(h.releasePending).toHaveBeenCalledExactlyOnceWith(1);
    }
  });

  it.each(["pending", "stopped"])("rejects an expired window ACK while the backend is %s without overwriting a newer lifecycle", async (stage) => {
    const h = closeHarness();
    await h.run();
    if (stage === "stopped") {
      h.backend.resolve("closed");
      await flushCloseCallbacks();
      expect(h.store.currentTransaction()?.phase).toBe("window_close_authorized");
    }
    expect(h.commitClosed).not.toHaveBeenCalled();
    h.isCurrent.mockReturnValue(false);
    await h.acknowledge();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.pendingAck()).toBeNull();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.canarySummary).not.toHaveBeenCalled();
    expect(h.record.mock.calls.some(([event]) => event.eventCode === "electron.workbench_close.completed")).toBe(false);
  });

  it("passes the captured frontend retirement closure to the existing backend owner without retiring it twice", async () => {
    const h = closeHarness();
    // Exercise the real stop adapter as well, so the trusted closure must reach
    // the lifecycle owner through the same argument rather than a second stop.
    const source = readFileSync(mainSourcePath, "utf8");
    const begin = source.indexOf("async function stopWorkbenchBackend(");
    const end = source.indexOf("\nfunction isRecoverableDesktopControlError(", begin);
    const lifecycle = vi.fn(async (..._args: unknown[]) => ({ accepted: true }));
    const adapter: Record<string, unknown> = { orchestrateLauncherLifecycle: lifecycle, Error };
    runInNewContext(transpileModule(source.slice(begin, end) + "\nglobalThis.stop = stopWorkbenchBackend;", {
      compilerOptions: { target: ScriptTarget.ES2022 }
    }).outputText, adapter);
    h.stop.mockImplementation(adapter.stop as typeof h.stop);
    await h.run();
    expect(h.captureBuilds).toHaveBeenCalledExactlyOnceWith("test-workspace");
    const captured = h.stop.mock.calls[0][4]?.background?.retireFrontendBuilds;
    expect(captured).toBe(h.retireBuilds);
    expect(h.retireBuilds).not.toHaveBeenCalled();
    expect(h.getOwner).toHaveBeenCalledExactlyOnceWith("test-workspace");
    expect(h.stop).toHaveBeenCalledOnce();
    expect(lifecycle).toHaveBeenCalledOnce();
    expect(lifecycle.mock.calls[0][0]).toBe("force-stop");
    expect(lifecycle.mock.calls[0][1]).toMatchObject({ init: { body: { deferWindowClose: true, confirmed: true } } });
    expect(lifecycle.mock.calls[0][2]).toBe("operator");
    expect(lifecycle.mock.calls[0][3]).toBe(h.stop.mock.calls[0][3]);
    expect(lifecycle.mock.calls[0][4]).toBe(h.stop.mock.calls[0][4]);
    await captured!();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.retireBuilds).toHaveBeenCalledOnce();
    expect(h.readback).not.toHaveBeenCalled();
  });

  it("retries at least two unconfirmed no-owner readbacks before completing on verified closure", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    h.readStatus.mockResolvedValueOnce({ observedState: "stopping" })
      .mockResolvedValueOnce({ observedState: "unknown" });
    await h.run();
    await h.acknowledge();
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.readStatus).toHaveBeenCalledWith("test-workspace");
    expect(h.readback).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(249);
    expect(h.readback).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.readback).toHaveBeenCalledTimes(2);
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.pending()).toBe(true);
    expect(h.canarySummary).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(250);
    expect(h.readback).toHaveBeenCalledTimes(3);
    expect(h.readback.mock.calls.every(([input]) => input.timeoutMs === 1000)).toBe(true);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.commitClosed).toHaveBeenCalledExactlyOnceWith(1);
    expect(h.pendingAck()).toBeNull();
    expect(h.retireBuilds).toHaveBeenCalledOnce();
  });

  it("keeps long unknown no-owner readbacks pending without delaying the window and stops when its epoch expires", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    h.readStatus.mockResolvedValue({ observedState: "unknown" });
    const requestedAt = Date.now();
    await h.run();
    expect(h.closed).toHaveBeenCalledExactlyOnceWith({ deadlineAt: requestedAt + 2000 });
    expect(Date.now()).toBe(requestedAt);
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.readback.mock.calls.length).toBeGreaterThan(2);
    expect(h.readback.mock.calls.every(([input]) => input.timeoutMs === 1000)).toBe(true);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.pending()).toBe(true);
    expect(h.canarySummary).not.toHaveBeenCalled();
    const readbacksBeforeSupersede = h.readback.mock.calls.length;
    h.isCurrent.mockReturnValue(false);
    await vi.advanceTimersByTimeAsync(250);
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.pendingAck()).toBeNull();
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.readback).toHaveBeenCalledTimes(readbacksBeforeSupersede);
    expect(h.pending()).toBe(true);
    expect(h.canarySummary).not.toHaveBeenCalled();
    expect(h.record.mock.calls.some(([event]) => event.eventCode === "electron.workbench_close.completed")).toBe(false);
  });

  it("accepts eventual verified no-owner closure after the original window deadline", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    h.readStatus.mockResolvedValue({ observedState: "stopping" });
    await h.run();
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.commitClosed).not.toHaveBeenCalled();
    h.readStatus.mockResolvedValue({ observedState: "closed" });
    await vi.advanceTimersByTimeAsync(250);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.canarySummary).toHaveBeenCalledOnce();
  });

  it.each(["status", "readback"])("hard-bounds a never-returning %s read at 1000ms and retries without delaying the window", async (stage) => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    if (stage === "status") h.readStatus.mockImplementationOnce(() => new Promise(() => undefined));
    else h.readback.mockImplementationOnce(() => new Promise(() => undefined));
    const requestedAt = Date.now();
    await h.run();
    await h.acknowledge();
    expect(h.closed).toHaveBeenCalledExactlyOnceWith({ deadlineAt: requestedAt + 2000 });
    expect(Date.now()).toBe(requestedAt);
    await vi.advanceTimersByTimeAsync(999);
    expect(h.readback).toHaveBeenCalledTimes(1);
    expect(h.commitClosed).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(h.readback.mock.calls[0][0].signal?.aborted).toBe(true);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    await vi.advanceTimersByTimeAsync(249);
    expect(h.readback).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.readback).toHaveBeenCalledTimes(2);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.retireBuilds).toHaveBeenCalledOnce();
  });

  it.each(["status", "readback", "frontend"])("exits a permanently stalled %s observation after its hard deadline when the epoch expires", async (stage) => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    if (stage === "status") h.readStatus.mockImplementation(() => new Promise(() => undefined));
    else if (stage === "readback") h.readback.mockImplementation(() => new Promise(() => undefined));
    else h.retireBuilds.mockImplementation(() => new Promise(() => undefined));
    await h.run();
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(999);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    h.isCurrent.mockReturnValue(false);
    await vi.advanceTimersByTimeAsync(251);
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.pendingAck()).toBeNull();
    expect(h.readback).toHaveBeenCalledTimes(1);
    expect(h.canarySummary).not.toHaveBeenCalled();
  });

  it.each(["false", "delayed"])("keeps a closed backend pending while captured frontend retirement is %s", async (stage) => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    const frontend = deferred<boolean>();
    if (stage === "false") h.retireBuilds.mockResolvedValueOnce(false).mockResolvedValueOnce(false);
    else h.retireBuilds.mockImplementationOnce(() => frontend.promise);
    const requestedAt = Date.now();
    await h.run();
    await h.acknowledge();
    expect(h.closed).toHaveBeenCalledOnce();
    expect(Date.now()).toBe(requestedAt);
    await vi.advanceTimersByTimeAsync(499);
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.pending()).toBe(true);
    expect(h.commitClosed).not.toHaveBeenCalled();
    if (stage === "delayed") frontend.resolve(true);
    await vi.advanceTimersByTimeAsync(1);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    const callsAtCompletion = h.retireBuilds.mock.calls.length;
    expect(callsAtCompletion).toBe(stage === "false" ? 3 : 1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(h.retireBuilds).toHaveBeenCalledTimes(callsAtCompletion);
    expect(h.canarySummary).toHaveBeenCalledOnce();
  });

  it("closes promptly and retries stalled admission while the original lifecycle remains current", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    const admission = deferred<void>();
    h.stop.mockImplementationOnce(() => admission.promise);
    h.getOwner.mockReturnValueOnce(undefined);
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1799);
    expect(h.store.currentTransaction()?.phase).toBe("backend_closing");
    await vi.advanceTimersByTimeAsync(1);
    await closing;
    expect(h.stop.mock.calls[0][3].aborted).toBe(true);
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.markPending).toHaveBeenCalledOnce();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "background_closing" });
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(250);
    expect(h.stop).toHaveBeenCalledTimes(2);
    expect(h.stop.mock.calls[1][2].requestId).toBe(h.stop.mock.calls[0][2].requestId);
    admission.resolve();
    await flushCloseCallbacks();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
  });

  it("joins a late admitted retirement rather than starting a second stop", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    h.stop.mockImplementationOnce(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(250);
    expect(h.stop).toHaveBeenCalledOnce();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
  });

  it("joins the original owner if it appears while the retry is in flight", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    let failRetry!: (error: Error) => void;
    const retry = new Promise<void>((_resolve, reject) => { failRetry = reject; });
    h.stop.mockImplementationOnce(() => new Promise(() => undefined)).mockImplementationOnce(() => retry);
    h.getOwner.mockReturnValueOnce(undefined);
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(250);
    expect(h.stop).toHaveBeenCalledTimes(2);
    failRetry(new Error("fetch failed"));
    await flushCloseCallbacks();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.stop).toHaveBeenCalledTimes(2);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
  });

  it("reports a permanent retry failure and releases the restart gate without claiming closure", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    h.stop.mockImplementationOnce(() => new Promise(() => undefined))
      .mockRejectedValueOnce(new Error("No captured native retirement identity is available."));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    await h.acknowledge();
    await vi.advanceTimersByTimeAsync(250);
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "backend_stop_admission_failed" });
    expect(h.pending()).toBe(false);
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.notify).toHaveBeenCalledWith("Vibelution", "后台回收未完成；请查看 Launcher 状态后重试。", "warning");
    await vi.advanceTimersByTimeAsync(2000);
    expect(h.stop).toHaveBeenCalledTimes(2);
  });

  it("waits for the real window acknowledgement when a retry fails during slow destruction", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    const destroy = deferred<void>();
    h.closed.mockImplementationOnce(() => destroy.promise);
    h.stop.mockImplementationOnce(() => new Promise(() => undefined))
      .mockRejectedValueOnce(new Error("No captured native retirement identity is available."));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(2050);
    expect(h.store.currentTransaction()?.phase).toBe("failed");
    expect(h.pendingAck()).not.toBeNull();
    expect(isWorkbenchStartBlockedByClose(false, h.store.currentTransaction(), h.pendingAck() !== null)).toBe(true);
    expect(h.record).not.toHaveBeenCalledWith(expect.objectContaining({ eventCode: "electron.workbench_close.window_closed_after_failure" }));
    destroy.resolve();
    await closing;
    await h.acknowledge();
    expect(h.pendingAck()).toBeNull();
    expect(isWorkbenchStartBlockedByClose(false, h.store.currentTransaction(), h.pendingAck() !== null)).toBe(false);
    expect(h.record).toHaveBeenCalledWith(expect.objectContaining({ eventCode: "electron.workbench_close.window_closed_after_failure" }));
  });

  it("acknowledges an already absent window and allows restart after backend retirement", async () => {
    const h = closeHarness();
    h.closed.mockResolvedValueOnce({ open: false });
    await h.run();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "background_closing", windowAcknowledged: true });
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
    expect(h.pendingAck()).toBeNull();
    expect(isWorkbenchStartBlockedByClose(false, h.store.currentTransaction(), false)).toBe(false);
  });

  it("keeps the gate until backend retirement finishes when the window cannot be destroyed", async () => {
    const h = closeHarness();
    h.closed.mockResolvedValueOnce({ open: true });
    await h.run();
    expect(h.store.currentTransaction()?.phase).toBe("background_closing");
    expect(h.pending()).toBe(true);
    expect(h.notify).toHaveBeenCalledOnce();
    h.backend.resolve("closed");
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "window_close_failed" });
    expect(h.pendingAck()).toBeNull();
    expect(h.pending()).toBe(false);
    expect(h.canarySummary).not.toHaveBeenCalled();
  });

  it("releases the window gate when both window destruction and the background retry fail", async () => {
    vi.useFakeTimers();
    const h = closeHarness({ owner: false });
    h.closed.mockResolvedValueOnce({ open: true });
    h.stop.mockImplementationOnce(() => new Promise(() => undefined))
      .mockRejectedValueOnce(new Error("No captured native retirement identity is available."));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    expect(h.pendingAck()).not.toBeNull();
    await vi.advanceTimersByTimeAsync(250);
    await flushCloseCallbacks();
    expect(h.store.currentTransaction()?.phase).toBe("failed");
    expect(h.pendingAck()).toBeNull();
    expect(h.pending()).toBe(false);
  });

  it("does not leave a phantom window acknowledgement after an admission failure with no close in flight", async () => {
    const h = closeHarness();
    h.stop.mockRejectedValueOnce(new Error("No captured native retirement identity is available."));
    await expect(h.run()).rejects.toThrow("No captured native retirement identity");
    expect(h.pendingAck()).toBeNull();
    expect(isWorkbenchStartBlockedByClose(false, h.store.currentTransaction(), false)).toBe(false);
  });

  it("retains a failed close acknowledgement for the actual native window close", async () => {
    const h = closeHarness();
    h.closeInFlight.mockReturnValue(true);
    h.stop.mockRejectedValueOnce(new Error("No captured native retirement identity is available."));
    await expect(h.run()).rejects.toThrow("No captured native retirement identity");
    expect(h.pendingAck()).not.toBeNull();
    await h.acknowledge();
    expect(h.pendingAck()).toBeNull();
    expect(h.record).toHaveBeenCalledWith(expect.objectContaining({ eventCode: "electron.workbench_close.window_closed_after_failure" }));
  });

  it("charges coordinator queue time against the original admission and window deadlines", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    const requestedAt = Date.now();
    h.coordinator.mockImplementation(async (_reason, run) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await run();
    });
    h.stop.mockImplementationOnce(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    expect(Date.now()).toBe(requestedAt + 1800);
    expect(h.stop.mock.calls[0][4]?.deadlineAt).toBe(requestedAt + 1800);
    expect(h.stop.mock.calls[0][3].aborted).toBe(true);
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.markPending).toHaveBeenCalledOnce();
  });

  it("never retries a timed-out close after its lifecycle is superseded", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    h.stop.mockImplementationOnce(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(1800);
    await closing;
    h.isCurrent.mockReturnValue(false);
    await vi.advanceTimersByTimeAsync(250);
    expect(h.stop).toHaveBeenCalledOnce();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "lifecycle_intent_superseded" });
    expect(h.commitClosed).not.toHaveBeenCalled();
  });

  it("preserves the non-Windows path that verifies backend and frontend retirement before closing", async () => {
    const h = closeHarness({ platform: "linux" });
    const readback = deferred<boolean>();
    h.readback.mockImplementationOnce(async (input) => {
      await input.readStatus();
      return await readback.promise;
    });
    const closing = h.run();
    await flushCloseCallbacks();
    expect(h.retireBuilds).toHaveBeenCalledOnce();
    expect(h.readStatus).toHaveBeenCalledWith("test-workspace");
    expect(h.store.currentTransaction()?.phase).toBe("backend_closing");
    expect(h.closed).not.toHaveBeenCalled();
    readback.resolve(true);
    await closing;
    expect(h.stop.mock.calls[0][4]).toBeUndefined();
    expect(h.markPending).not.toHaveBeenCalled();
    expect(h.getOwner).not.toHaveBeenCalled();
    expect(h.commitClosed).toHaveBeenCalledWith(1);
    expect(h.commitClosed.mock.invocationCallOrder[0]).toBeLessThan(h.closed.mock.invocationCallOrder[0]!);
    expect(h.store.currentTransaction()?.phase).toBe("window_close_authorized");
    expect(h.pendingAck()).not.toHaveProperty("projectionEpoch");
    await h.acknowledge();
    expect(h.commitClosed).toHaveBeenCalledExactlyOnceWith(1);
    expect(h.store.currentTransaction()?.phase).toBe("succeeded");
  });

  it.each(["frontend", "readback"])("preserves non-Windows rejection when %s does not retire", async (stage) => {
    const h = closeHarness({ platform: "linux" });
    if (stage === "frontend") h.retireBuilds.mockResolvedValueOnce(false);
    else h.readStatus.mockResolvedValueOnce({ observedState: "stopping" });
    await expect(h.run()).rejects.toThrow(stage === "frontend" ? "Owned frontend build processes did not retire" : "did not settle closed");
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.commitClosed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "backend_stop_timeout" });
  });
});

describe("Electron main transactional Workbench close", () => {
  it("persists close evidence locally instead of awaiting the backend being stopped", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const request = source.slice(source.indexOf("async function requestTransactionalWorkbenchClose("), source.indexOf("async function stopWorkbenchBackend("));
    const settlement = source.slice(source.indexOf("async function acknowledgeTransactionalWorkbenchClose("), source.indexOf("function writeWorkbenchCloseCanarySummary("));
    const failureStart = source.indexOf("async function handleTransactionalWorkbenchCloseFailure(");
    const failure = source.slice(failureStart, source.indexOf("\nasync function ", failureStart + 1));
    for (const closeSource of [request, settlement, failure]) {
      expect(closeSource).toContain("recordSupervisorEventFallbackLocally({");
      expect(closeSource).not.toContain("await recordElectronSupervisorEvent(");
    }
    expect(request).toContain("activeWorkProbeMs");
    expect(request).toContain("backendStopMs");
    expect(settlement).toContain("elapsedMs");
  });

  it("advertises the Electron close capability instead of reusing only Launcher capabilities", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('WORKBENCH_CLOSE_TRANSACTION_CAPABILITY = "workbench_close.transaction.v1"');
    expect(source).toContain("function desktopSessionCapabilities(bootstrap: LauncherBootstrapResult): string[]");
    expect(source).toContain("capabilities: desktopSessionCapabilities(bootstrap)");
  });

  it("owns the close transaction state machine in Electron main", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('from "./lifecycle/workbenchCloseTransactionStore.js"');
    expect(source).toContain("const mainWorkbenchCloseStore = new MainWorkbenchCloseTransactionStore();");
    expect(source).toContain("shouldInterceptWorkbenchClose: () => !shutdownApproved");
    expect(source).toContain("requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(source).toContain("mainWorkbenchCloseStore.submit(");
    expect(source).toContain('mode: "force",\n      requestId: randomUUID(),');
    expect(source).toContain("mainWorkbenchCloseStore.backendStopped(");
    expect(source).toContain("await provider.approveWorkbenchCloseOnce()");
    expect(source).toContain("buttons: [\"重试\", \"仍关闭窗口\"]");
    const providerStart = source.indexOf("function createWindowProvider(");
    const providerEnd = source.indexOf("\nfunction createConversationBadgeIcon", providerStart);
    const providerSource = source.slice(providerStart, providerEnd);
    expect(providerSource).toContain("requestTransactionalWorkbenchClose(paths, bootstrap)");
    expect(providerSource).not.toContain('requestDesktopShellExit("workbench_window_close")');
    expect(closeStoreSource).toContain("confirmation_required");
    expect(closeStoreSource).toContain("window_close_authorized");
  });

  it("stops the backend through the lifecycle supervisor before authorizing the window close", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const stopStart = source.indexOf("async function stopWorkbenchBackend(");
    const stopEnd = source.indexOf("\nasync function ", stopStart + 1);
    const stopSource = source.slice(stopStart, stopEnd);

    expect(source).toContain("electron.workbench_close.backend_stopping");
    expect(source).toContain("stopWorkbenchBackend(paths, bootstrap, transaction, signal, fastCloseTiming)");
    expect(source).toContain('const activeWorkState: ActiveWorkProbeState = "unknown"');
    const request = source.slice(source.indexOf("async function requestTransactionalWorkbenchClose("), stopStart);
    expect(request).not.toContain("fetchLauncherActiveWorkStatus(");
    expect(request).not.toContain("confirmWorkbenchForceClose(");
    expect(request).not.toContain("resolveDesktopActionLoopContext(");
    expect(stopSource).toContain("orchestrateLauncherLifecycle(operation");
    expect(stopSource).toContain("requestId: transaction.requestId");
    expect(stopSource).toContain("closeId: transaction.closeId");
    expect(stopSource).toContain("deferWindowClose: true");
    expect(stopSource).not.toContain("runWorkbenchLifecycle({");
    expect(source).toContain("!shouldDeferOrchestratedWindowClose(payload)");
    expect(source).toContain('from "./lifecycle/workbenchBackendCloseReadiness.js"');
    expect(source).toContain("waitForWorkbenchBackendSettledForWindowClose({");
    expect(request).toContain("deadlineAt: requestedAt + WORKBENCH_CLOSE_BACKEND_WAIT_MS, forceAt: requestedAt + WORKBENCH_CLOSE_FORCE_AFTER_MS");
    expect(request).toContain("Math.max(1, fastCloseTiming.deadlineAt - Date.now())");
    expect(request).toContain('process.platform === "win32"');
    expect(request).toContain("readStatus: async () => readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot)");
    expect(stopSource).toContain('transaction.mode === "force" ? "operator" : "window-close", signal, fastCloseTiming');
    expect(source).toContain("timeoutMs: closeDeadline.remainingMs()");
    expect(source).toContain("mainWorkbenchCloseStore.fail(");
    expect(source).toContain('"backend_stop_timeout"');
    expect(source).toContain("onWorkbenchClosed: () =>");
    expect(source).toContain("mainWorkbenchCloseStore.windowClosed(transaction.closeId)");
    expect(source).toContain('if (settled.phase === "failed")');
    expect(source).toContain('"electron.workbench_close.window_closed_after_failure"');
    expect(source).toContain("desktopSessionRevision");
  });

  it("opens the named Workbench only in canary mode and writes proof after the closed acknowledgement", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("desktopCliArgs.workbenchCloseCanary");
    expect(source).toContain("async function openWorkbenchForCloseCanary(");
    expect(source).toContain('operation: "start"');
    expect(source).toContain("await openWorkbenchForCloseCanary(paths, launcherBootstrap, windowProvider);");
    expect(source).toContain("function writeWorkbenchCloseCanarySummary(");
    expect(source).toContain("desktopWorkbenchCloseCanarySummaryPath(paths.workspaceRoot)");
    expect(source).toContain("desktopWorkbenchCloseCanarySummary({");
  });

  it("keeps the Python desktop action claim loop stopped after the T6 reversal", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("startDesktopActionLoop stays");
    expect(source).not.toMatch(
      /if \(desktopCliArgs\.workbenchCloseCanary\) \{\s*await openWorkbenchForCloseCanary\(paths, launcherBootstrap, windowProvider\);\s*return;\s*\}\s*startDesktopActionLoop\(paths, launcherBootstrap, windowProvider\);/
    );
  });

  it("keeps the registered Launcher session intact while opening a desktop action", () => {
    const source = readFileSync(mainSourcePath, "utf8");
    const actionOpenStart = source.indexOf("async function openWorkbenchAtCurrentLauncherUrl(");
    const actionOpenEnd = source.indexOf("\nasync function reportManagedWindowState", actionOpenStart);
    const actionOpenSource = source.slice(actionOpenStart, actionOpenEnd);

    expect(actionOpenStart).toBeGreaterThanOrEqual(0);
    expect(actionOpenEnd).toBeGreaterThan(actionOpenStart);
    expect(actionOpenSource).not.toContain("bootstrapLauncherIfEnabled(paths)");
    expect(actionOpenSource).toContain("payloadUrl || bootstrap.workbenchUrl");
    expect(actionOpenSource).toContain("resolveWorkbenchUrl(desktopEnvironment(), payloadUrl || bootstrap.workbenchUrl)");
    expect(actionOpenSource).toContain("currentWorkbenchUrl = workbenchUrl;");
    expect(actionOpenSource).toContain("await provider.openOrFocusWorkbench(workbenchUrl)");
    expect(source).toContain("const workbenchUrl = currentWorkbenchUrl || resolveWorkbenchUrl(desktopEnv, launcherBootstrap?.workbenchUrl)");
    expect(source).toContain(
      "openOrFocusWorkbench: (payload) => openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, payload)"
    );
  });

  it("keeps the control context recovery helper for session heartbeat and workbench close", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain("async function recoverWorkbenchCloseControlContext(");
    expect(source).toContain("owner.resolve({ forceRefresh: options.forceControlTokenRefresh, signal: options.signal })");
    expect(source).toContain("const context = desktopControlContextForLocalClose(bootstrap);");
    const recovery = source.slice(source.indexOf("async function recoverDesktopControlContext("), source.indexOf("async function recoverWorkbenchCloseControlContext("));
    expect(recovery).not.toContain("runtimeSceneBridge = null");
  });

  it("records supervisor evidence for untracked closes and fail-open paths", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('from "./lifecycle/supervisorEventFallback.js"');
    expect(source).toContain("appendSupervisorEventFallback(workspaceRoot, {");
    expect(source).toContain('"electron.workbench_close.untracked_window_closed"');
    expect(source).toContain('"electron.workbench_close.fail_open_user_declined"');
  });
});
