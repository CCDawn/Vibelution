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

  it("gives branch cleanup the stop budget and preserves uncertain-mutation handling", () => {
    const apiStart = mainSource.indexOf("async function orchestrateLauncherApi");
    const apiEnd = mainSource.indexOf("function scheduleLauncherStatusCliRefresh", apiStart);
    const apiBody = mainSource.slice(apiStart, apiEnd);
    const bridgeStart = apiBody.indexOf("const raw = await runPythonJsonBridge");
    const bridgeBody = apiBody.slice(bridgeStart, apiBody.indexOf("const parsed", bridgeStart));

    expect(bridgeBody).toContain('path === "branch-instances/cleanup"');
    expect(bridgeBody).toContain("PYTHON_JSON_BRIDGE_ISOLATED_STOP_TIMEOUT_MS");
    expect(bridgeBody).toContain('mutation: method !== "GET"');
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
    expect(branchBody).toContain("deadlineAt: result.deadlineAt");
    expect(branchBody).toContain("renewIsolatedOwnerLease");
    expect(branchBody).toContain("runIsolatedRegistryMutation");
    expect(branchBody).toContain("observeIsolatedReady");
    expect(branchBody).toContain("observeIsolatedError");
    const isolatedMutationStart = mainSource.indexOf("async function runIsolatedRegistryMutation");
    const isolatedMutationBody = mainSource.slice(isolatedMutationStart, branchStart);
    expect(isolatedMutationBody).toContain("await ensureFrontendRelease({");
    expect(isolatedMutationBody).toContain("workspaceRoot: target.projectRoot");
    expect(mainSource).toContain("from \"./process/isolatedInstanceSupervisor.js\"");
    expect(mainSource).toContain("from \"./lifecycle/isolatedInstanceRegistryHost.js\"");
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
    expect(readyBody).not.toContain("waitForWorkbenchLifecycleReady");
    expect(readyBody).not.toContain("readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot, lease.commandId)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.isCurrent(lease)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.claimReady(lease)");
    expect(readyBody).toContain("launcherLifecycleSupervisor.completeReady(lease)");
    expect(readyBody).not.toContain("waitForWorkbenchHttp");
    expect(lifecycleBody).toContain("mainLineBackendIsReusable");
    expect(lifecycleBody).toContain("packagedDesktopShellIsStale");
    expect(lifecycleBody).toContain("已打开工作台窗口。");

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

  it("waits for the Electron control plane before dispatching startup and second-instance lifecycle commands", () => {
    const bootstrapIndex = mainSource.indexOf("launcherBootstrap = await bootstrapMainOwnedLauncher(paths);");
    const readyResolveIndex = mainSource.indexOf("resolveLauncherControlPlaneReady?.();");
    expect(bootstrapIndex).toBeGreaterThan(0);
    expect(readyResolveIndex).toBeGreaterThan(bootstrapIndex);

    const projectSlotStart = mainSource.indexOf("async function applyPendingProjectSlot");
    const projectSlotEnd = mainSource.indexOf("if (runPrimaryWhenReady)", projectSlotStart);
    const projectSlotBody = mainSource.slice(projectSlotStart, projectSlotEnd);
    expect(projectSlotBody).toContain("await launcherControlPlaneReady");

    const secondInstanceStart = mainSource.indexOf('app.on("second-instance"');
    const secondInstanceEnd = mainSource.indexOf('app.on("open-url"', secondInstanceStart);
    const secondInstanceBody = mainSource.slice(secondInstanceStart, secondInstanceEnd);
    expect(secondInstanceBody).toContain("await launcherControlPlaneReady");

    const firstLifecycleIndex = mainSource.indexOf("const firstLifecycle =");
    const firstLifecycleEnd = mainSource.indexOf("// T6:", firstLifecycleIndex);
    const firstLifecycleBody = mainSource.slice(firstLifecycleIndex, firstLifecycleEnd);
    expect(firstLifecycleBody).toContain(
      "await handleSecondInstanceLifecycleCommand(firstLifecycle, desktopLifecycleProvenance)"
    );
    expect(firstLifecycleBody).not.toContain("void handleSecondInstanceLifecycleCommand(firstLifecycle)");
  });

  it("keeps command ids on reused main-line starts and accepted stop results", () => {
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleEnd = mainSource.indexOf("async function orchestrateBranchInstanceLifecycle", lifecycleStart);
    const lifecycleBody = mainSource.slice(lifecycleStart, lifecycleEnd);
    const reuseStart = lifecycleBody.indexOf("mainLineBackendIsReusable(paths.workspaceRoot)");
    const intentLeaseIndex = lifecycleBody.indexOf("const intentLease");
    const reuseEnd = lifecycleBody.indexOf("// A reachable but non-reusable backend", reuseStart);
    const reuseBody = lifecycleBody.slice(reuseStart, reuseEnd);

    expect(intentLeaseIndex).toBeGreaterThan(0);
    expect(intentLeaseIndex).toBeLessThan(reuseStart);
    expect(reuseBody).toContain("commandId: randomUUID()");
    expect(reuseBody).toContain("launcherLifecycleSupervisor.isCurrent(intentLease)");
    expect(lifecycleBody).toContain("mutation.value.accepted && !mutation.value.commandId?.trim()");
    expect(lifecycleBody).toContain("commandId: randomUUID()");
    expect(lifecycleBody).toContain('desiredState === "closed"');
    expect(lifecycleBody).toContain("&& result.commandId");
    expect(lifecycleBody).toContain("approveWorkbenchCloseOnce");
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

  it("checks the verified release before reusing a live workbench", () => {
    const readyStart = mainSource.indexOf("async function openWorkbenchAfterLifecycleReady");
    const readyBody = mainSource.slice(readyStart, readyStart + 700);
    expect(readyBody).toContain("await refreshLiveWorkbenchUrl(paths)");
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody.indexOf("await ensureLatestLauncher(")).toBeGreaterThanOrEqual(0);
    expect(lifecycleBody.indexOf("await ensureLatestLauncher(")).toBeLessThan(
      lifecycleBody.indexOf("await mainLineBackendIsReusable(paths.workspaceRoot)")
    );
    expect(lifecycleBody).toContain("mainLineBackendIsReachable(paths.workspaceRoot)");
    expect(lifecycleBody).toContain('lifecycleOperation = "restart"');
    expect(lifecycleBody).toContain("app.relaunch()");
    const productStart = mainSource.indexOf("async function startOrFocusWorkbenchFromProductEntryOnShell");
    const productBody = mainSource.slice(productStart, productStart + 1200);
    expect(productBody).toContain('orchestrateLauncherLifecycle("start", { schemaVersion: 1, path: "open" })');
    expect(productBody).not.toContain("waitForHttp");
    expect(productBody).not.toContain("openOrFocus:");
    const secondStart = mainSource.indexOf("async function requestOpenWorkbenchFromSecondInstance");
    const secondBody = mainSource.slice(secondStart, secondStart + 900);
    expect(secondBody).toContain("await startOrFocusWorkbenchFromProductEntryOnShell()");
  });

  it("never lets a window-level or forwarded stop abort an in-flight restart", () => {
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    // The provenance-aware entry keeps operator commands as the default.
    expect(lifecycleBody).toContain('provenance: LauncherLifecycleProvenance = "operator"');
    // Only the plain stop operation relaxes its supersede semantics.
    expect(lifecycleBody).toContain("joinDecisionForLauncherLifecycleStop(operation, provenance)");
    expect(lifecycleBody).toContain("beginIntentWithOptions");
    expect(lifecycleBody).toContain('"joined-in-flight-restart"');
    expect(lifecycleBody).toContain("joined_in_flight_restart");
    expect(lifecycleBody).toContain("waitForInFlightRestartSettlement");

    const stopStart = mainSource.indexOf("async function stopWorkbenchBackend(");
    const stopEnd = mainSource.indexOf("\nasync function ", stopStart + 1);
    const stopBody = mainSource.slice(stopStart, stopEnd);
    // A normal window close joins/waits; a confirmed force close keeps superseding.
    expect(stopBody).toContain('transaction.mode === "force" ? "operator" : "window-close"');

    const secondInstanceStart = mainSource.indexOf('app.on("second-instance"');
    const secondInstanceEnd = mainSource.indexOf('app.on("open-url"', secondInstanceStart);
    const secondInstanceBody = mainSource.slice(secondInstanceStart, secondInstanceEnd);
    expect(secondInstanceBody).toContain("resolveSingleInstanceProvenance(additionalData)");
    expect(secondInstanceBody).toContain("secondInstanceProvenance");
    expect(secondInstanceBody).toContain("provenance: LauncherLifecycleProvenance = \"operator\"");

    // A permanently failed restart lease must not keep absorbing joins.
    const lifecycleFailedIndex = lifecycleBody.indexOf("mutation.outcome === \"failed\"");
    expect(lifecycleFailedIndex).toBeGreaterThanOrEqual(0);
    expect(lifecycleBody.slice(lifecycleFailedIndex, lifecycleFailedIndex + 400)).toContain(
      "clearSlotIfCurrent(intentLease)",
    );
  });

  it("gives an in-flight rebuild-and-start the same forwarded-stop protection as a restart", () => {
    // The settle helper drives both the window-close wait and the join
    // classification: rebuild-and-start must count as in-flight there, or a
    // forwarded stop would still abort a CLI rebuild 1-5s into its mutation.
    const settleStart = mainSource.indexOf("function inFlightRestartLeaseSettled");
    const settleEnd = mainSource.indexOf("\nfunction ", settleStart + 1);
    const settleBody = mainSource.slice(settleStart, settleEnd);
    expect(settleBody).toContain('snapshot.operation === "restart"');
    expect(settleBody).toContain('snapshot.operation === "rebuild-and-start"');

    // The join no-op stays an accepted result so the forwarding side settles
    // without a failure while the rebuild keeps running.
    const lifecycleStart = mainSource.indexOf("async function orchestrateLauncherLifecycle");
    const lifecycleBody = mainSource.slice(lifecycleStart, mainSource.indexOf("async function orchestrateBranchInstanceLifecycle"));
    expect(lifecycleBody).toContain("joined_in_flight_restart");

    // The provenance gates keep the operator protections intact: only the
    // plain stop with forwarded/window-close provenance relaxes, so an
    // operator stop and force-stop still supersede a rebuild unconditionally.
    const decisionStart = mainSource.indexOf("function joinDecisionForLauncherLifecycleStop");
    const decisionEnd = mainSource.indexOf("\n}", decisionStart);
    const decisionBody = mainSource.slice(decisionStart, decisionEnd);
    expect(decisionBody).toContain('if (operation !== "stop")');
    expect(decisionBody).toContain('provenance === "forwarded"');
    expect(decisionBody).toContain('provenance === "window-close"');
    expect(decisionBody).toContain('return { joinInFlightRestart: false, waitForInFlightRestart: false };');
  });

  it("routes the forwarded close-window intent into the controlled workbench close transaction", () => {
    const secondInstanceStart = mainSource.indexOf("async function handleSecondInstanceLifecycleCommand");
    const secondInstanceEnd = mainSource.indexOf('app.on("open-url"', secondInstanceStart);
    const secondInstanceBody = mainSource.slice(secondInstanceStart, secondInstanceEnd);
    // The Runtime Manager queue forwards close_workbench without stopManager as
    // the close-window token; the desktop lane must act on it instead of
    // ignoring it, and it must run the same controlled close transaction the
    // workbench window close button uses - never an app-shell "stop".
    expect(secondInstanceBody).toContain('command === "close-window"');
    const closeWindowStart = secondInstanceBody.indexOf('command === "close-window"');
    const closeWindowEnd = secondInstanceBody.indexOf("return;", closeWindowStart);
    const closeWindowBody = secondInstanceBody.slice(closeWindowStart, closeWindowEnd);
    expect(closeWindowBody).toContain(
      "requestTransactionalWorkbenchClose(createDesktopPathsForApp(), launcherBootstrap)"
    );
    // The close-window lane is not misrouted through the app-shell lifecycle
    // orchestrator (close-window is not a supervised lifecycle operation).
    expect(closeWindowBody).not.toContain("orchestrateLauncherLifecycle");
    // No visible console and no subprocess may be launched on this lane;
    // comment lines are stripped so prose cannot trip the assertion.
    const closeWindowCode = closeWindowBody
      .split("\n")
      .filter((line) => !line.trim().startsWith("//"))
      .join("\n");
    expect(closeWindowCode).not.toMatch(/AllocConsole|spawn|execFile|powershell|cmd\.exe/i);
  });
});
