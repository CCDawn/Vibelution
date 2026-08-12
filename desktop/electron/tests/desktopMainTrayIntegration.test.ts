import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main tray integration", () => {
  it("keeps one tray alive and routes native-parity tray actions through launcher control APIs", () => {
    expect(mainSource).toContain('from "./tray/desktopTray.js"');
    expect(mainSource).toContain("let desktopTray:");
    expect(mainSource).toContain("desktopTray = createDesktopTray(paths,");
    expect(mainSource).toContain("windowProvider?.openLauncher()");
    expect(mainSource).not.toContain("electron.launcher.window.opened");
    expect(mainSource).toContain('"/api/launcher/branch-instances/start"');
    expect(mainSource).toContain('"/api/launcher/branch-instances/stop"');
    expect(mainSource).toContain('runTrayLauncherPost("/api/launcher/restart"');
    expect(mainSource).toContain('runTrayLauncherPost("/api/launcher/rebuild-and-start"');
    expect(mainSource).toContain("runTrayLauncherStatus()");
    expect(mainSource).toContain('path: "/api/launcher/force-stop"');
    expect(mainSource).toContain("requestDesktopShellExit()");
    expect(mainSource).toContain("electronStartupStage = \"tray_ready\"");
    expect(mainSource).toContain("Keep the lightweight tray app running");

    const trayStart = mainSource.indexOf("desktopTray = createDesktopTray(paths,");
    const trayEnd = mainSource.indexOf("claimElectronDesktopShellOwner(paths.workspaceRoot)", trayStart);
    const traySource = mainSource.slice(trayStart, trayEnd);
    expect(traySource).toContain("quit:");
    expect(traySource).toContain("stopAll:");
    expect(traySource).toContain("startInstance:");
    expect(traySource).toContain("stopInstance:");
    expect(traySource).toContain("listInstances:");
    expect(traySource).toContain("showStatus:");
    expect(traySource).toContain("requestDesktopShellExit()");
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

  it("fails closed before authorization but fails open after shutdown was approved", () => {
    expect(mainSource).toContain("DESKTOP_SHELL_EXIT_BUDGET_MS");
    expect(mainSource).not.toContain("failOpenOnActiveWorkError: true");
    expect(mainSource).toContain("pendingWorkbenchCloseAck = null");
    expect(mainSource).toContain("forcing Electron quit");
    expect(mainSource).toContain("stopOwnedPythonLauncherService()");
    expect(mainSource).toContain("stop python launcher on exit budget fail-open");
    expect(mainSource).toContain('可先用托盘“停止全部”');
    expect(mainSource).toContain("WORKBENCH_CLOSE_AUTHORIZATION_MAX_WAIT_MS");
  });
});
