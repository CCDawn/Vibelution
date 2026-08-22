import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main tray integration", () => {
  it("routes tray actions through launcher control without direct main-workbench restart menu paths", () => {
    expect(mainSource).toContain('from "./tray/desktopTray.js"');
    expect(mainSource).toContain("desktopTray = createDesktopTray(paths,");
    expect(mainSource).toContain("listInstances:");
    expect(mainSource).toContain("restartLauncher:");
    expect(mainSource).toContain("runTrayRestartLauncher");
    expect(mainSource).toContain("stopAllManagedRuntimeTrees");
    expect(mainSource).toContain("exitAndRelaunchLauncherShell");
    expect(mainSource).toContain("ensureLatestLauncher");
    expect(mainSource).toContain('decision === "ensure-and-relaunch"');
    expect(mainSource).toContain("runTrayBranchInstance");
    expect(mainSource).toContain("runTrayStopAll");
    const trayStart = mainSource.indexOf("desktopTray = createDesktopTray(paths,");
    const trayEnd = mainSource.indexOf("startPeriodicShellFreshnessWatch", trayStart);
    const traySource = mainSource.slice(trayStart, trayEnd);
    expect(traySource).toContain("stopAll:");
    expect(traySource).toContain("classifyTrayBranchInstances(launcherStateStore.projectBranchInstances())");
    expect(traySource).toContain("launcherStateStore.projectFreshness()");
    expect(traySource).not.toContain("fetchLauncherBranchInstances");
    expect(traySource).not.toContain("fetchLauncherFreshness");
    expect(traySource).not.toContain("quit:");
    expect(traySource).not.toContain("requestDesktopShellExit");
    expect(mainSource).not.toContain("restartProject:");
    expect(mainSource).not.toContain("rebuildAndStart:");
    expect(mainSource).not.toContain("showStatus:");
    expect(mainSource).not.toContain("runTrayLauncherStatus");
    expect(mainSource).toContain('orchestrateLauncherLifecycle("force-stop"');
    expect(mainSource).toContain("refreshPackagedDesktopShellIfStale");
    expect(mainSource).toContain("startPeriodicShellFreshnessWatch");
  });

  it("refreshes a stale launcher control token before denying tray quit", () => {
    const quitStart = mainSource.indexOf("async function requestDesktopShellExit");
    const quitEnd = mainSource.indexOf("function notifyDesktopTray", quitStart);
    const quitSource = mainSource.slice(quitStart, quitEnd);
    expect(quitSource).toContain("resolveQuitActiveWorkStatus");
    expect(quitSource).toContain("forceControlTokenRefresh");
    expect(quitSource).toContain("QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS");
    expect(quitSource).toContain("退出壳并停止全部任务");
    expect(mainSource).toContain("const QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS = 20_000");
  });

  it("destroys the tray only after shutdown is approved", () => {
    const beforeQuitStart = mainSource.indexOf('app.on("before-quit"');
    const windowAllClosedStart = mainSource.indexOf('app.on("window-all-closed"', beforeQuitStart);
    const beforeQuitSource = mainSource.slice(beforeQuitStart, windowAllClosedStart);

    expect(beforeQuitSource).toContain("if (shutdownApproved)");
    expect(mainSource).toContain("claimElectronDesktopShellOwner(paths.workspaceRoot)");
    expect(mainSource).toContain("stopLeftoverPythonLauncher: stopOwnedPythonLauncherService");
    expect(mainSource).toContain("shouldInterceptInstanceClose: () => !shutdownApproved");
    expect(mainSource).not.toContain("stopPythonLauncher: ownershipMode === \"started\"");
  });

  it("claims the desktop shell owner before creating the tray", () => {
    const claimIdx = mainSource.indexOf("claimElectronDesktopShellOwner(paths.workspaceRoot)");
    const trayIdx = mainSource.indexOf("desktopTray = createDesktopTray(paths,");
    expect(claimIdx).toBeGreaterThan(-1);
    expect(trayIdx).toBeGreaterThan(-1);
    expect(claimIdx).toBeLessThan(trayIdx);
  });

  it("records tray force-interrupt evidence when restart-all runs under FORCE_INTERRUPT", () => {
    expect(mainSource).toContain("ACTIVE_WORK_POLICY_FORCE_INTERRUPT");
    expect(mainSource).toContain("runTrayRestartAll");
    expect(mainSource).toContain("recordTrayForceInterruptEvidence");
    expect(mainSource).toContain("writeTrayRestartAllPending");
  });

  it("routes tray stop-all through forced shell exit instead of aborting on control fetch failed", () => {
    const stopAllStart = mainSource.indexOf("async function runTrayStopAll");
    const stopAllEnd = mainSource.indexOf("\nasync function ", stopAllStart + 1);
    const stopAllSource = mainSource.slice(stopAllStart, stopAllEnd);
    expect(stopAllSource).toContain("requestForcedDesktopShellExit");
    expect(stopAllSource).not.toContain("postLauncherControl");
    expect(stopAllSource).not.toContain("停止全部失败");

    const forcedStart = mainSource.indexOf("async function requestForcedDesktopShellExit");
    const forcedEnd = mainSource.indexOf("\nasync function ", forcedStart + 1);
    const forcedSource = mainSource.slice(forcedStart, forcedEnd);
    expect(forcedSource).toContain("shouldNotifyForceStopControlFailure");
    expect(forcedSource).toContain("executeApprovedDesktopShellShutdown");
    expect(forcedSource).toContain('orchestrateLauncherLifecycle("force-stop"');
  });

  it("stops the tray force flows when the operator cancels authorization", () => {
    expect(mainSource).toContain("isForceLifecycleAuthorizationDenied");
    const restartLauncherStart = mainSource.indexOf("async function runTrayRestartLauncher");
    const restartLauncherEnd = mainSource.indexOf("\nasync function ", restartLauncherStart + 1);
    expect(mainSource.slice(restartLauncherStart, restartLauncherEnd)).toContain(
      "已取消全部停止，当前窗口、运行时和任务均保留。"
    );
    const restartAllStart = mainSource.indexOf("async function runTrayRestartAll");
    const restartAllEnd = mainSource.indexOf("\nasync function ", restartAllStart + 1);
    expect(mainSource.slice(restartAllStart, restartAllEnd)).toContain(
      "已取消全部重启，当前窗口、运行时和任务均保留。"
    );
    const forcedStart = mainSource.indexOf("async function requestForcedDesktopShellExit");
    const forcedEnd = mainSource.indexOf("\nasync function ", forcedStart + 1);
    expect(mainSource.slice(forcedStart, forcedEnd)).toContain(
      "已取消退出，当前窗口、运行时和任务均保留。"
    );
  });

  it("stops every live isolated row before approved shell exit", () => {
    expect(mainSource).toContain("captureShutdownInstanceIds");
    expect(mainSource).toContain("stopIsolatedInstancesForApprovedShutdown");
    const captureStart = mainSource.indexOf("async function captureShutdownIsolatedInstanceIds");
    const captureEnd = mainSource.indexOf("\nasync function stopIsolatedInstancesForApprovedShutdown", captureStart);
    const captureSource = mainSource.slice(captureStart, captureEnd);
    expect(captureStart).toBeGreaterThan(-1);
    expect(captureEnd).toBeGreaterThan(captureStart);
    expect(captureSource).toContain("Promise.allSettled");
    expect(captureSource).toContain("launcherStateStore.refresh");
    expect(captureSource).toContain("fetchLauncherBranchInstances");
    expect(captureSource).toContain("readRegistry(instancesRegistryPath())");
    expect(captureSource).toContain("registryEntriesToShutdownInstanceSnapshots");
    expect(captureSource).toContain("withDesktopShellExitTimeout");
    expect(captureSource).not.toContain('snapshot.freshness === "fresh"');
    const quitStart = mainSource.indexOf("async function requestDesktopShellExit");
    const quitEnd = mainSource.indexOf("function notifyDesktopTray", quitStart);
    const quitSource = mainSource.slice(quitStart, quitEnd);
    const quitApprovedStart = quitSource.indexOf("runApproved: async (decision)");
    const quitFailOpenStart = quitSource.indexOf("failOpenAfterApproval:", quitApprovedStart);
    const quitApprovedSource = quitSource.slice(quitApprovedStart, quitFailOpenStart);
    const quitTimeoutStart = quitApprovedSource.indexOf("await withDesktopShellExitTimeout(");
    const quitBudgetIndex = quitApprovedSource.lastIndexOf("DESKTOP_SHELL_EXIT_BUDGET_MS");
    const quitExitSource = quitApprovedSource.slice(quitTimeoutStart, quitBudgetIndex);
    expect(quitApprovedStart).toBeGreaterThan(-1);
    expect(quitFailOpenStart).toBeGreaterThan(quitApprovedStart);
    expect(quitTimeoutStart).toBeGreaterThan(-1);
    expect(quitBudgetIndex).toBeGreaterThan(quitTimeoutStart);
    expect(quitExitSource).toContain("await bestEffortStopIsolatedInstancesForShutdown");
    expect(quitExitSource).toContain("await executeApprovedDesktopShellShutdown");
    expect(quitExitSource.indexOf("await bestEffortStopIsolatedInstancesForShutdown")).toBeLessThan(
      quitExitSource.indexOf("await executeApprovedDesktopShellShutdown")
    );
    expect(quitApprovedSource).toContain("DESKTOP_SHELL_EXIT_BUDGET_MS");
    const forcedStart = mainSource.indexOf("async function requestForcedDesktopShellExit");
    const forcedEnd = mainSource.indexOf("\nasync function ", forcedStart + 1);
    const forcedSource = mainSource.slice(forcedStart, forcedEnd);
    const forcedTimeoutStart = forcedSource.indexOf("await withDesktopShellExitTimeout(");
    const forcedBudgetIndex = forcedSource.lastIndexOf("DESKTOP_SHELL_EXIT_BUDGET_MS");
    const forcedExitSource = forcedSource.slice(forcedTimeoutStart, forcedBudgetIndex);
    expect(forcedStart).toBeGreaterThan(-1);
    expect(forcedEnd).toBeGreaterThan(forcedStart);
    expect(forcedTimeoutStart).toBeGreaterThan(-1);
    expect(forcedBudgetIndex).toBeGreaterThan(forcedTimeoutStart);
    expect(forcedExitSource).toContain("await bestEffortStopIsolatedInstancesForShutdown");
    expect(forcedExitSource).toContain("await executeApprovedDesktopShellShutdown");
    expect(forcedExitSource.indexOf("await bestEffortStopIsolatedInstancesForShutdown")).toBeLessThan(
      forcedExitSource.indexOf("await executeApprovedDesktopShellShutdown")
    );
    expect(forcedSource).toContain("DESKTOP_SHELL_EXIT_BUDGET_MS");
    const failOpenStart = quitSource.indexOf("failOpenAfterApproval:", quitApprovedStart);
    const failOpenSource = quitSource.slice(failOpenStart);
    expect(failOpenSource).not.toContain("stopIsolatedInstancesForApprovedShutdown()");
    expect(failOpenSource).toContain("retrySuppressed: true");
    expect(mainSource).toContain("observedState");
  });
});
