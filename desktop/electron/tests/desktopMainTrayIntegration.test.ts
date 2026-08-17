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
});
