import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main tray integration", () => {
  it("keeps one tray alive and routes full tray actions through launcher control", () => {
    expect(mainSource).toContain('from "./tray/desktopTray.js"');
    expect(mainSource).toContain("let desktopTray:");
    expect(mainSource).toContain("desktopTray = createDesktopTray(paths,");
    expect(mainSource).toContain("windowProvider?.openLauncher()");
    expect(mainSource).toContain("listInstances:");
    expect(mainSource).toContain("getFreshness:");
    expect(mainSource).toContain("restartLauncher:");
    expect(mainSource).toContain("startInstance:");
    expect(mainSource).toContain("stopInstance:");
    expect(mainSource).toContain("restartProject:");
    expect(mainSource).toContain("rebuildAndStart:");
    expect(mainSource).toContain("showStatus:");
    expect(mainSource).toContain("stopAll:");
    expect(mainSource).toContain("runTrayLauncherPost");
    expect(mainSource).toContain("runTrayStopAll");
    expect(mainSource).toContain("runTrayLauncherStatus");
    expect(mainSource).toContain("maybeRestoreTrayRestartAllPending");
    expect(mainSource).toContain("startPeriodicShellFreshnessWatch");
    expect(mainSource).toContain("electronStartupStage = \"tray_ready\"");
    expect(mainSource).toContain("Keep the lightweight tray app running");

    const trayStart = mainSource.indexOf("desktopTray = createDesktopTray(paths,");
    const trayEnd = mainSource.indexOf("startPeriodicShellFreshnessWatch()", trayStart);
    const traySource = mainSource.slice(trayStart, trayEnd);
    expect(traySource).toContain("openLauncher:");
    expect(traySource).toContain("listInstances:");
    expect(traySource).toContain("stopAll:");
    expect(mainSource).toContain("refreshPackagedDesktopShellIfStale");
    expect(mainSource).toContain("scheduleDesktopShellRefresh");
    expect(mainSource).toContain("decidePeriodicDesktopShellRefresh");
    expect(mainSource).toContain("reapManagedRuntimeOnDesktopStart");
    expect(mainSource).toContain("handleSecondInstanceLifecycleCommand(firstLifecycle)");
  });

  it("destroys the tray only after shutdown is approved", () => {
    const beforeQuitStart = mainSource.indexOf('app.on("before-quit"');
    const windowAllClosedStart = mainSource.indexOf('app.on("window-all-closed"', beforeQuitStart);
    const beforeQuitSource = mainSource.slice(beforeQuitStart, windowAllClosedStart);

    expect(beforeQuitSource).toContain("if (shutdownApproved)");
    expect(mainSource).toContain("claimElectronDesktopShellOwner(paths.workspaceRoot)");
    expect(mainSource).toContain("releaseElectronDesktopShellOwner");
  });

  it("records tray force-interrupt evidence when restart-all runs under FORCE_INTERRUPT", () => {
    expect(mainSource).toContain("ACTIVE_WORK_POLICY_FORCE_INTERRUPT");
    expect(mainSource).toContain("runTrayRestartAll");
    expect(mainSource).toContain("recordTrayForceInterruptEvidence");
    expect(mainSource).toContain("writeTrayRestartAllPending");
  });
});
