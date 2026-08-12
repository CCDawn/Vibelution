import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("Electron main tray integration", () => {
  it("keeps one tray alive and routes tray actions through existing window and shutdown owners", () => {
    expect(mainSource).toContain('from "./tray/desktopTray.js"');
    expect(mainSource).toContain("let desktopTray:");
    expect(mainSource).toContain("desktopTray = createDesktopTray(paths,");
    expect(mainSource).toContain("windowProvider?.openLauncher()");
    expect(mainSource).toContain("requestDesktopShellExit()");
  });

  it("destroys the tray only after shutdown is approved", () => {
    const beforeQuitStart = mainSource.indexOf('app.on("before-quit"');
    const windowAllClosedStart = mainSource.indexOf('app.on("window-all-closed"', beforeQuitStart);
    const beforeQuitSource = mainSource.slice(beforeQuitStart, windowAllClosedStart);

    expect(beforeQuitSource).toContain("if (shutdownApproved)");
    expect(beforeQuitSource).toContain("desktopTray?.destroy()");
    expect(beforeQuitSource).toContain("desktopTray = null");
  });
});
