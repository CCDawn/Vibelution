import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const launcherWindowSource = readFileSync(
  fileURLToPath(new URL("../src/windows/launcherWindow.ts", import.meta.url)),
  "utf8",
);

describe("Electron main Launcher IPC facade", () => {
  it("registers a control-window-only launcher invoke handler", () => {
    expect(mainSource).toContain("IPC_CHANNELS.launcherInvoke");
    expect(mainSource).toContain("from \"./protocol/launcherIpcHost.js\"");
    expect(mainSource).toContain("resolveLauncherIpcHost()");
  });

  it("validates the launcher invoke sender against the Launcher control origin only", () => {
    const invokeStart = mainSource.indexOf("IPC_CHANNELS.launcherInvoke");
    const invokeEnd = mainSource.indexOf("});", invokeStart);
    const handlerSource = mainSource.slice(invokeStart, invokeEnd);
    expect(handlerSource).toContain("assertTrustedIpcSender");
    expect(handlerSource).not.toContain("trustedIpcOrigins()");
    expect(mainSource).toContain("launcherIpcTrustedOrigins()");
    const trustedStart = mainSource.indexOf("function launcherIpcTrustedOrigins");
    const trustedEnd = mainSource.indexOf("}", trustedStart);
    expect(mainSource.slice(trustedStart, trustedEnd)).toContain("resolveLauncherWindowUrl");
  });

  it("keeps the workbench sender away from Launcher control IPC", () => {
    expect(launcherWindowSource).toContain('"--vibelution-window-role=launcher-control"');
    expect(preloadSource).toContain('process.argv.includes("--vibelution-window-role=launcher-control")');
    expect(preloadSource).toContain("launcherInvoke");
    expect(preloadSource).toContain("getLauncherState");
    expect(preloadSource).toContain("refreshLauncherState");
    expect(preloadSource).toContain("IPC_CHANNELS.refreshLauncherState");
    expect(preloadSource).toContain("onLauncherStateChanged");
    expect(preloadSource).toContain("removeListener(IPC_CHANNELS.launcherStateChanged, wrapped)");
    expect(launcherWindowSource).toContain('additionalArguments: ["--vibelution-window-role=launcher-control"]');
    expect(mainSource).toContain("launcherIpcTrustedOrigins");
  });

  it("does not require a workbench control token before serving launcher status", () => {
    const hostSource = readFileSync(fileURLToPath(new URL("../src/protocol/launcherIpcHost.ts", import.meta.url)), "utf8");
    const invokeStart = hostSource.indexOf("async invoke(");
    const contextStart = hostSource.indexOf("await input.resolveContext()", invokeStart);
    const statusApi = hostSource.indexOf('"status"', hostSource.indexOf("const LAUNCHER_API_PATHS"));
    expect(statusApi).toBeGreaterThan(0);
    expect(statusApi).toBeLessThan(contextStart);
    expect(mainSource).toContain("createLocalLauncherStatusSnapshot");
    expect(mainSource).toContain("resolveLocalStatus");
    expect(mainSource).toContain("launcherStateStore.projectStatus()");
    expect(mainSource).toContain("launcherStateStore.projectBranchInstances()");
    expect(mainSource).toContain("return launcherStateStore.snapshot()");
    expect(mainSource).toContain('orchestrateLauncherApi("state-refresh"');
    expect(mainSource).toContain("body: { electronWindowInstanceIds }");
    expect(mainSource).toContain("nextReconcileAt: state.nextReconcileAt");
    expect(mainSource).toContain('refresh("reconcile_deadline")');
    expect(mainSource).toContain('refresh("user_recheck")');
    expect(mainSource).toContain("IPC_CHANNELS.refreshLauncherState");
    expect(mainSource).toContain("reconcileDeadlineScheduler.clear()");
    expect(mainSource).not.toContain('orchestrateLauncherApi("branch-instances?cleanupMetadata=1"');
    const storeStart = mainSource.indexOf("const launcherStateStore = new LauncherStateStore(");
    const storeEnd = mainSource.indexOf("const WORKBENCH_CLOSE_BACKEND_WAIT_MS", storeStart);
    expect(mainSource.slice(storeStart, storeEnd).match(/orchestrateLauncherApi\(/g)).toHaveLength(1);
  });

  it("refreshes state from debounced file hints and stat-only safety checks", () => {
    expect(mainSource).toContain("scheduleLauncherStateFileHint");
    expect(mainSource).toContain("}, 200)");
    expect(mainSource).toContain("statSync(path)");
    expect(mainSource).toContain("state.json");
    expect(mainSource).toContain("ports.json");
    expect(mainSource).toContain("instances.json");
    const statLoopStart = mainSource.indexOf("launcherStateStatTimer = setInterval");
    const statLoopEnd = mainSource.indexOf("}, 30_000);", statLoopStart);
    const statLoop = mainSource.slice(statLoopStart, statLoopEnd);
    expect(statLoop).toContain("if (changed)");
    expect(statLoop).not.toContain("orchestrateLauncherApi");
    expect(mainSource).toContain('app.on("will-quit"');
    expect(mainSource).toContain("stopLauncherStateFileHints()");
  });

  it("routes the current checkout through the main supervisor and keeps isolated READY guarded", () => {
    expect(mainSource).toContain("isCurrentCheckoutInstance(instanceId)");
    expect(mainSource).toContain("provider.openOrFocusWorkbench(workbenchUrl)");
    expect(mainSource).toContain("refreshLiveWorkbenchUrl");
    expect(mainSource).toContain("resolveWorkbenchUrlFromBridge");
    expect(mainSource).toContain("return workbenchLoopbackUrl();");
    const branchStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const branchBody = mainSource.slice(branchStart, mainSource.indexOf("async function orchestrateLauncherApi"));
    expect(branchBody).toContain('operation === "start" || operation === "restart"');
    expect(branchBody).toContain("isCurrentCheckoutInstance(instanceId)");
    expect(branchBody).toContain("orchestrateLauncherLifecycle(operation, payload)");
    expect(branchBody).toContain("superviseIsolatedInstanceStart");
    expect(branchBody).toContain("ISOLATED_INSTANCE_READY_WAIT_MS");
    expect(branchBody).toContain('operation: "observe-error"');
    expect(branchBody).toContain('operation: "observe-ready"');
    expect(mainSource).toContain("from \"./process/isolatedInstanceSupervisor.js\"");
  });

  it("owns main and isolated lifecycle observers through one revisioned supervisor", () => {
    expect(mainSource).toContain('from "./lifecycle/launcherLifecycleSupervisor.js"');
    expect(mainSource).toContain("const launcherLifecycleSupervisor = new LauncherLifecycleSupervisor()");
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody).toContain("launcherLifecycleSupervisor.beginIntent");
    expect(lifecycleBody).toContain("launcherLifecycleSupervisor.executeMutation");
    expect(lifecycleBody).toContain("launcherLifecycleSupervisor.bindCommand");
    expect(lifecycleBody).toContain("scheduleLauncherStatusCliRefresh");
    expect(lifecycleBody).toContain("signal: intentLease.signal");

    const readyStart = mainSource.indexOf("async function openWorkbenchAfterLifecycleReady");
    const readyBody = mainSource.slice(readyStart, readyStart + 1800);
    expect(readyBody).toContain("waitForWorkbenchLifecycleReady");
    expect(readyBody).toContain("signal: lease.signal");
    expect(readyBody).toContain("expectedGeneration: lease.generation");
    expect(readyBody).toContain("readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot, lease.commandId)");
    expect(readyBody).toContain("expectedGeneration: lease.generation");
    expect(readyBody).toContain("readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot, lease.commandId)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.isCurrent(lease)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.claimReady(lease)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.completeReady(lease)");
    expect(readyBody).not.toContain("waitForWorkbenchHttp");

    const branchStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const branchBody = mainSource.slice(branchStart, branchStart + 4200);
    expect(branchBody).toContain("launcherLifecycleSupervisor.beginIntent");
    expect(branchBody).toContain("launcherLifecycleSupervisor.bindCommand");
    expect(branchBody).toContain("lease,");
    expect(branchBody).toContain("isCurrent:");
    expect(branchBody).toContain("claimReady:");
    expect(branchBody).toContain("completeReady:");
    expect(branchBody).toContain("signal: intentLease.signal");
  });

  it("authorizes every main and isolated force operation before creating its lifecycle intent", () => {
    expect(mainSource).toContain('from "./lifecycle/forceLifecycleAuthorization.js"');
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody.indexOf("authorizeLauncherForceLifecycle")).toBeGreaterThanOrEqual(0);
    expect(lifecycleBody.indexOf("authorizeLauncherForceLifecycle")).toBeLessThan(
      lifecycleBody.indexOf("launcherLifecycleSupervisor.beginIntent")
    );

    const branchStart = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle");
    const branchBody = mainSource.slice(branchStart, mainSource.indexOf("async function orchestrateLauncherApi"));
    expect(branchBody).toContain("authorizeLauncherForceLifecycle");
    expect(mainSource).toContain("electron.lifecycle.force_authorized");
    expect(mainSource).toContain("requestId: authorization.requestId");
    expect(mainSource).toContain("activeWorkState: authorization.probeState");
  });

  it("closes Electron workbench windows on stop instead of waiting for Python to own them", () => {
    expect(mainSource).toContain("closeOrchestratedWorkbenchWindow");
    expect(mainSource).toContain("approveWorkbenchCloseOnce");
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody).toContain("shouldRefreshBeforeLifecycle");
    expect(lifecycleBody).toContain('desiredState === "closed"');
    expect(lifecycleBody).toContain("launcherLifecycleSupervisor.isCurrent(lease)");
    expect(lifecycleBody).toContain("approveWorkbenchCloseOnce");
  });

  it("routes approved desktop shutdown through the same lifecycle supervisor", () => {
    const shutdownStart = mainSource.indexOf("async function stopMainRuntimeForApprovedShutdown");
    const shutdownBody = mainSource.slice(shutdownStart, mainSource.indexOf("async function requestDesktopShellExit", shutdownStart));
    expect(shutdownBody).toContain('orchestrateLauncherLifecycle("shutdown"');
    expect(mainSource).toContain("stopManagedRuntime: stopMainRuntimeForApprovedShutdown");
    const managedStart = mainSource.indexOf("async function stopManagedRuntime()");
    const managedBody = mainSource.slice(managedStart, mainSource.indexOf("\nfunction desktopPythonPath", managedStart));
    expect(managedBody).toContain("launcherLifecycleSupervisor.executeMutation");
    expect(managedBody).toContain('operation: "shutdown"');
  });

  it("restores tray instances through the main and isolated lifecycle supervisors", () => {
    const restoreStart = mainSource.indexOf("async function restoreTrayRestartAllPending");
    const restoreBody = mainSource.slice(restoreStart, mainSource.indexOf("async function maybeRestoreTrayRestartAllPending", restoreStart));
    expect(restoreBody).toContain('orchestrateLauncherLifecycle("start"');
    expect(restoreBody).toContain('orchestrateBranchInstanceLifecycle("start"');
    expect(restoreBody).not.toContain("runWorkbenchLifecycle({");
    expect(restoreBody).not.toContain("runBranchInstanceBridge({");
  });

  it("routes the first product-entry open through the supervised live-or-start path", () => {
    const startupOpen = mainSource.indexOf("if (pendingOpenWorkbenchRequest &&");
    const startupBody = mainSource.slice(startupOpen, startupOpen + 500);
    expect(startupBody).toContain("await startOrFocusWorkbenchFromProductEntryOnShell()");
    expect(startupBody).not.toContain("windowProvider.openOrFocusWorkbench()");
  });

  it("refreshes the live workbench URL after start instead of waiting on a stale bootstrap port", () => {
    const readyStart = mainSource.indexOf("async function openWorkbenchAfterLifecycleReady");
    const readyBody = mainSource.slice(readyStart, readyStart + 700);
    expect(readyBody).toContain("await refreshLiveWorkbenchUrl(paths)");
    const productStart = mainSource.indexOf("async function startOrFocusWorkbenchFromProductEntryOnShell");
    const productBody = mainSource.slice(productStart, productStart + 1200);
    expect(productBody).toContain("await refreshLiveWorkbenchUrl(");
    expect(productBody).toContain('orchestrateLauncherLifecycle("start", { schemaVersion: 1, path: "open" })');
    const secondStart = mainSource.indexOf("async function requestOpenWorkbenchFromSecondInstance");
    const secondBody = mainSource.slice(secondStart, secondStart + 900);
    expect(secondBody).toContain("await startOrFocusWorkbenchFromProductEntryOnShell()");
  });
});
