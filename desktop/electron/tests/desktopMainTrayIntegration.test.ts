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
    expect(mainSource).toContain("runTrayLauncherPost");
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
    expect(mainSource).not.toContain("stopPythonLauncher: ownershipMode === \"started\"");
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
});
