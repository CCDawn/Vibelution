import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { ScriptTarget, transpileModule } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MainWorkbenchCloseTransactionStore } from "../src/lifecycle/workbenchCloseTransactionStore.js";
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
  const stop = vi.fn(async () => undefined);
  const closed = vi.fn(async () => undefined);
  const record = vi.fn();
  const sandbox: Record<string, unknown> = {
    AbortSignal, Error, performance,
    windowProvider: { approveWorkbenchCloseOnce: closed },
    desktopLifecycleCoordinator: { request: async (_reason: string, run: () => Promise<void>) => run() },
    resolveDesktopActionLoopContext: context,
    currentDesktopSessionId: () => "stable-session", desktopEnvironment: () => ({}),
    fetchLauncherActiveWorkStatus: probe,
    resolveQuitActiveWorkStatus, isActiveWorkProbeAuthFailure,
    createDesktopShellExitDeadline, withDesktopShellExitTimeout,
    ACTIVE_WORK_STATUS_TIMEOUT_MS: 8000, WORKBENCH_CLOSE_ACTIVE_WORK_BUDGET_MS: 12000, WORKBENCH_CLOSE_BACKEND_WAIT_MS: 30000,
    mainWorkbenchCloseStore: new MainWorkbenchCloseTransactionStore(),
    confirmWorkbenchForceClose: confirm,
    recordSupervisorEventFallbackLocally: record,
    stopWorkbenchBackend: stop,
    waitForWorkbenchBackendSettledForWindowClose: async () => true,
    pendingWorkbenchCloseAck: null, workbenchCloseBackendStopInFlight: null
  };
  runInNewContext(transpileModule(source.slice(begin, end) + "\nglobalThis.runClose = requestTransactionalWorkbenchClose;", {
    compilerOptions: { target: ScriptTarget.ES2022 }
  }).outputText, sandbox);
  return { context, probe, confirm, stop, closed, record, run: () => (sandbox.runClose as (paths: object, bootstrap: object) => Promise<void>)({}, {}) };
}

afterEach(() => vi.useRealTimers());

describe("Workbench close active-work recovery", () => {
  it("refreshes a rejected cached token and closes idle work without confirmation", async () => {
    const h = closeHarness();
    h.probe.mockRejectedValueOnce(new Error("launcher active-work status request failed: 403"));
    await h.run();
    expect(h.context).toHaveBeenLastCalledWith({}, expect.objectContaining({ forceControlTokenRefresh: true }));
    expect(h.probe.mock.calls.map(([input]) => input.controlToken)).toEqual(["cached", "fresh"]);
    expect(h.confirm).not.toHaveBeenCalled();
    expect(h.stop).toHaveBeenCalledOnce();
    expect(h.closed).toHaveBeenCalledOnce();
  });

  it("preserves task protection when the recovered probe finds active work", async () => {
    const h = closeHarness();
    h.probe.mockRejectedValueOnce(new Error("401 unauthorized"));
    h.probe.mockResolvedValueOnce({ state: "active", message: "work is running" });
    await h.run();
    expect(h.confirm).toHaveBeenCalledWith(expect.anything(), "active");
    expect(h.stop).not.toHaveBeenCalled();
    expect(h.closed).not.toHaveBeenCalled();
  });

  it("keeps unknown state protected after two authentication failures", async () => {
    const h = closeHarness();
    h.probe.mockRejectedValue(new Error("403 forbidden"));
    await h.run();
    expect(h.probe).toHaveBeenCalledTimes(2);
    expect(h.confirm).toHaveBeenCalledWith(expect.anything(), "unknown");
    expect(h.stop).not.toHaveBeenCalled();
  });

  it("recovers a timeout without showing a confirmation when the retry is idle", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    h.probe.mockImplementationOnce(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(8001);
    await closing;
    expect(h.probe).toHaveBeenCalledTimes(2);
    expect(h.confirm).not.toHaveBeenCalled();
    expect(h.closed).toHaveBeenCalledOnce();
    expect(h.record).toHaveBeenCalledWith(expect.objectContaining({
      eventCode: "electron.workbench_close.active_work_checked",
      fields: expect.objectContaining({ desktopSessionId: "stable-session", activeWorkState: "idle", probeAttempts: 2 })
    }));
  });

  it("retries a stalled probe and aborts both attempts within one 12 second budget", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    h.probe.mockImplementation(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(8001);
    expect(h.probe).toHaveBeenCalledTimes(2);
    expect(h.probe.mock.calls[0][0].signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(4000);
    await closing;
    expect(h.probe.mock.calls[1][0].signal?.aborted).toBe(true);
    expect(h.confirm).toHaveBeenCalledWith(expect.anything(), "unknown");
    expect(h.stop).not.toHaveBeenCalled();
  });

  it("bounds control-token acquisition too and never probes after it has expired", async () => {
    vi.useFakeTimers();
    const h = closeHarness();
    h.context.mockImplementation(() => new Promise(() => undefined));
    const closing = h.run();
    await vi.advanceTimersByTimeAsync(12001);
    await closing;
    expect(h.context).toHaveBeenCalledTimes(2);
    expect(h.probe).not.toHaveBeenCalled();
    expect(h.confirm).toHaveBeenCalledWith(expect.anything(), "unknown");
    expect(h.stop).not.toHaveBeenCalled();
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
    expect(source).toContain("mainWorkbenchCloseStore.confirm(");
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
    expect(source).toContain("stopWorkbenchBackend(paths, bootstrap, transaction, signal)");
    expect(source).toContain('let activeWorkState: ActiveWorkProbeState = "unknown"');
    expect(source).toContain("activeWorkState = status.state");
    expect(source).toContain("mainWorkbenchCloseStore.confirm(transaction.closeId, transaction.requestId!)");
    expect(stopSource).toContain("orchestrateLauncherLifecycle(operation");
    expect(stopSource).toContain("requestId: transaction.requestId");
    expect(stopSource).toContain("closeId: transaction.closeId");
    expect(stopSource).toContain("deferWindowClose: true");
    expect(stopSource).not.toContain("runWorkbenchLifecycle({");
    expect(source).toContain("!shouldDeferOrchestratedWindowClose(payload)");
    expect(source).toContain('from "./lifecycle/workbenchBackendCloseReadiness.js"');
    expect(source).toContain("waitForWorkbenchBackendSettledForWindowClose({");
    expect(source).toContain("createDesktopShellExitDeadline(WORKBENCH_CLOSE_BACKEND_WAIT_MS)");
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
