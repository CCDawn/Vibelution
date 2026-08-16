import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main tray integration", () => {
  it("keeps one tray alive and routes simplified tray actions through launcher lifecycle coordinators", () => {
    expect(mainSource).toContain('from "./tray/desktopTray.js"');
    expect(mainSource).toContain("let desktopTray:");
    expect(mainSource).toContain("desktopTray = createDesktopTray(paths,");
    expect(mainSource).toContain("windowProvider?.openLauncher()");
    expect(mainSource).toContain("restartAll:");
    expect(mainSource).toContain("quitAll:");
    expect(mainSource).toContain("runTrayRestartAll");
    expect(mainSource).toContain("runTrayQuitAll");
    expect(mainSource).toContain("requestForcedDesktopShellExit");
    expect(mainSource).toContain("maybeRestoreTrayRestartAllPending");
    expect(mainSource).toContain("startPeriodicShellFreshnessWatch");
    expect(mainSource).toContain("captureRunningInstanceIds");
    expect(mainSource).toContain("writeTrayRestartAllPending");
    expect(mainSource).not.toContain("listInstances:");
    expect(mainSource).not.toContain("getFreshness:");
    expect(mainSource).not.toContain("restartLauncher:");
    expect(mainSource).not.toContain("runTrayStopAll");
    expect(mainSource).toContain('orchestrateLauncherLifecycle("force-stop"');
    expect(mainSource).toContain("electronStartupStage = \"tray_ready\"");
    expect(mainSource).toContain("Keep the lightweight tray app running");

    const trayStart = mainSource.indexOf("desktopTray = createDesktopTray(paths,");
    const trayEnd = mainSource.indexOf("claimElectronDesktopShellOwner(paths.workspaceRoot)", trayStart);
    const traySource = mainSource.slice(trayStart, trayEnd);
    expect(traySource).toContain("openLauncher:");
    expect(traySource).toContain("restartAll:");
    expect(traySource).toContain("quitAll:");
    expect(traySource).not.toContain("stopAll:");
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
    expect(beforeQuitSource).toContain("releaseElectronDesktopShellOwner");
    expect(beforeQuitSource).toContain("desktopTray?.destroy()");
    expect(beforeQuitSource).toContain("desktopTray = null");
  });

  it("records forced tray exits without relying on the normal active-work deny path", () => {
    expect(mainSource).toContain("ACTIVE_WORK_POLICY_FORCE_INTERRUPT");
    expect(mainSource).toContain("electron.tray.quit_all.force_interrupt");
    expect(mainSource).toContain("electron.tray.restart_all.force_interrupt");
    expect(mainSource).toContain("forced: true");
    expect(mainSource).toContain("stopManagedRuntime()");
    expect(mainSource).toContain('operation: "shutdown"');
  });
});
