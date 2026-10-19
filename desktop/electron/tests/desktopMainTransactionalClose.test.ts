import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MainWorkbenchCloseTransactionStore, type MainWorkbenchCloseTransaction } from "../src/lifecycle/workbenchCloseTransactionStore.js";
import { createDesktopShellExitDeadline, withDesktopShellExitTimeout } from "../src/shutdown/desktopShellExit.js";
import { isActiveWorkProbeAuthFailure, resolveQuitActiveWorkStatus } from "../src/shutdown/shutdownCoordinator.js";

const mainSourcePath = fileURLToPath(new URL("../src/main.ts", import.meta.url));
const closeStoreSource = readFileSync(
  fileURLToPath(new URL("../src/lifecycle/workbenchCloseTransactionStore.ts", import.meta.url)),
  "utf8",
);

function closeHarness() {
  const source = readFileSync(mainSourcePath, "utf8");
  const begin = source.indexOf("async function requestTransactionalWorkbenchClose(");
  const end = source.indexOf("\nasync function stopWorkbenchBackend(", begin);
  const context = vi.fn(async (_bootstrap: unknown, options: { forceControlTokenRefresh?: boolean; signal?: AbortSignal } = {}) => ({
    launcherOrigin: "http://127.0.0.1:1234", controlToken: options.forceControlTokenRefresh ? "fresh" : "cached", desktopSessionId: "stable-session"
  }));
  const probe = vi.fn(async (_input: { controlToken: string; signal?: AbortSignal }) => ({ state: "idle", message: "" }));
  const confirm = vi.fn(async () => false);
  const stop = vi.fn(async (_paths: object, _bootstrap: object, _transaction: MainWorkbenchCloseTransaction, _signal: AbortSignal, _timing: { deadlineAt: number; forceAt: number }) => undefined);
  const closed = vi.fn(async (_options?: { deadlineAt?: number }) => undefined);
  const record = vi.fn();
  const store = new MainWorkbenchCloseTransactionStore();
  const coordinator = vi.fn(async (_reason: string, run: () => Promise<void>) => run());
  const readStatus = vi.fn(async (_workspaceRoot: string) => ({ observedState: "closed" }));
  const readback = vi.fn(async (input: { readStatus: () => Promise<unknown>; timeoutMs: number; signal: AbortSignal }) => {
    await input.readStatus();
    return true;
  });
  const retireBuilds = vi.fn(async () => true);
  const sandbox: Record<string, unknown> = {
    AbortSignal, Date, Error, performance, randomUUID: () => "explicit-close-request",
    process: { platform: "win32" }, WORKBENCH_CLOSE_BACKEND_WAIT_MS: 1800, WORKBENCH_CLOSE_FORCE_AFTER_MS: 1200,
    WORKBENCH_CLOSE_TOTAL_WAIT_MS: 2000,
    windowProvider: { approveWorkbenchCloseOnce: closed },
    desktopLifecycleCoordinator: { request: coordinator },
    resolveDesktopActionLoopContext: context,
    currentDesktopSessionId: () => "stable-session", desktopEnvironment: () => ({}),
    fetchLauncherActiveWorkStatus: probe,
    resolveQuitActiveWorkStatus, isActiveWorkProbeAuthFailure,
    createDesktopShellExitDeadline, withDesktopShellExitTimeout,
    captureFrontendBuildRetirement: () => retireBuilds,
    mainWorkbenchCloseStore: store,
    confirmWorkbenchForceClose: confirm,
    recordSupervisorEventFallbackLocally: record,
    stopWorkbenchBackend: stop,
    waitForWorkbenchBackendSettledForWindowClose: readback,
    readRuntimeManagerLauncherStatusSummary: readStatus,
    pendingWorkbenchCloseAck: null, workbenchCloseBackendStopInFlight: null
  };
  runInNewContext(transpileModule(source.slice(begin, end) + "\nglobalThis.runClose = requestTransactionalWorkbenchClose;", {
    compilerOptions: { target: ScriptTarget.ES2022 }
  }).outputText, sandbox);
  return { context, probe, confirm, stop, closed, record, store, coordinator, readback, readStatus, retireBuilds,
    run: () => (sandbox.runClose as (paths: object, bootstrap: object) => Promise<void>)({ workspaceRoot: "test-workspace" }, {}) };
}

afterEach(() => vi.useRealTimers());

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
    expect(h.store.currentTransaction()?.phase).toBe("window_close_authorized");
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
    expect(h.stop.mock.calls[0][4]).toEqual({ deadlineAt: requestedAt + 1800, forceAt: requestedAt + 1200 });
    expect(h.readback.mock.calls[0][0].timeoutMs).toBe(900);
    expect(h.readback.mock.calls[0][0].signal).toBe(h.stop.mock.calls[0][3]);
    expect(h.closed).toHaveBeenCalledWith({ deadlineAt: requestedAt + 2000 });
  });

  it("authorizes window close only after the file-only final readback settles", async () => {
    const h = closeHarness();
    let finishReadback!: (settled: boolean) => void;
    h.readback.mockImplementationOnce(async (input) => {
      await input.readStatus();
      return await new Promise((resolve) => { finishReadback = resolve; });
    });
    const closing = h.run();
    await vi.waitFor(() => expect(h.readStatus).toHaveBeenCalledWith("test-workspace"));
    expect(h.store.currentTransaction()?.phase).toBe("backend_closing");
    expect(h.closed).not.toHaveBeenCalled();
    finishReadback(true);
    await closing;
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.record).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "electron.workbench_close.window_authorized"
    }));
  });

  it("does not authorize window close when backend stopping fails", async () => {
    const h = closeHarness();
    h.stop.mockRejectedValueOnce(new Error("owned process still running"));
    await expect(h.run()).rejects.toThrow("owned process still running");
    expect(h.readback).not.toHaveBeenCalled();
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "backend_stop_timeout" });
  });

  it("waits for exact owned frontend build retirement before authorizing the window", async () => {
    const h = closeHarness();
    h.retireBuilds.mockResolvedValueOnce(false);
    await expect(h.run()).rejects.toThrow("Owned frontend build processes did not retire");
    expect(h.stop).toHaveBeenCalledOnce();
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.readback).not.toHaveBeenCalled();
  });

  it("does not report close success when final readback is unsettled", async () => {
    const h = closeHarness();
    h.readback.mockResolvedValueOnce(false);
    await expect(h.run()).rejects.toThrow("did not settle closed");
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()?.phase).toBe("failed");
    expect(h.record.mock.calls.some(([event]) => event.eventCode === "electron.workbench_close.window_authorized")).toBe(false);
  });

  it.each(["backend stop", "final readback"])("fails a stalled %s within the same 1800ms budget", async (stage) => {
    vi.useFakeTimers();
    const h = closeHarness();
    if (stage === "backend stop") h.stop.mockImplementationOnce(() => new Promise(() => undefined));
    else h.readback.mockImplementationOnce(() => new Promise(() => undefined));
    const failure = h.run().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(1800);
    expect((await failure as Error).message).toContain("workbench close timed out after 1800ms");
    expect(h.stop.mock.calls[0][3].aborted).toBe(true);
    expect(h.closed).not.toHaveBeenCalled();
    expect(h.store.currentTransaction()).toMatchObject({ phase: "failed", failureCode: "backend_stop_timeout" });
    expect(h.record.mock.calls.some(([event]) => event.eventCode === "electron.workbench_close.window_authorized")).toBe(false);
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
    expect(source.includes("await fetchLauncherControlToken({ launcherOrigin, signal: options.signal })")).toBe(true);
    expect(source).toContain("context = await resolveDesktopActionLoopContext(bootstrap);");
    expect(source).toContain("runtimeSceneBridge = null;");
  });

  it("records supervisor evidence for untracked closes and fail-open paths", () => {
    const source = readFileSync(mainSourcePath, "utf8");

    expect(source).toContain('from "./lifecycle/supervisorEventFallback.js"');
    expect(source).toContain("appendSupervisorEventFallback(workspaceRoot, {");
    expect(source).toContain('"electron.workbench_close.untracked_window_closed"');
    expect(source).toContain('"electron.workbench_close.fail_open_user_declined"');
  });
});
