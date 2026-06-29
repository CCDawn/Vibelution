import { beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import type { DesktopPaths } from "../src/paths.js";

const browserWindowOptions: Array<Record<string, unknown>> = [];
const loadedUrls: string[] = [];
const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

vi.mock("electron", () => ({
  BrowserWindow: vi.fn().mockImplementation((options: Record<string, unknown>) => {
    browserWindowOptions.push(options);
    return {
      loadURL: vi.fn((url: string) => {
        loadedUrls.push(url);
        return Promise.resolve();
      })
    };
  })
}));

const { createLauncherWindow } = await import("../src/windows/launcherWindow.js");
const { createWorkbenchWindow } = await import("../src/windows/workbenchWindow.js");

const desktopPaths: DesktopPaths = {
  schemaVersion: 1,
  desktopBundleRoot: "C:/Program Files/Vibelution/resources/app.asar/dist",
  resourcesRoot: "C:/Program Files/Vibelution/resources",
  workspaceRoot: "C:/Users/17533/Desktop/Vibelution",
  userDataRoot: "C:/Users/17533/AppData/Roaming/Vibelution"
};

describe("Electron desktop window icons", () => {
  beforeEach(() => {
    browserWindowOptions.length = 0;
    loadedUrls.length = 0;
  });

  it("uses the shared Vibelution icon for the Launcher window", () => {
    createLauncherWindow("http://127.0.0.1:8765/launcher", desktopPaths);

    expect(browserWindowOptions[0]).toMatchObject({
      title: "Vibelution Launcher",
      icon: "C:\\Users\\17533\\Desktop\\Vibelution\\assets\\icons\\vibelution.ico",
      backgroundColor: "#f7fafc"
    });
    expect(loadedUrls).toEqual(["http://127.0.0.1:8765/launcher"]);
  });

  it("uses the shared Vibelution icon for the Workbench window", () => {
    createWorkbenchWindow("http://127.0.0.1:8000", desktopPaths);

    expect(browserWindowOptions[0]).toMatchObject({
      title: "Vibelution Workbench",
      icon: "C:\\Users\\17533\\Desktop\\Vibelution\\assets\\icons\\vibelution.ico",
      backgroundColor: "#f7fafc"
    });
    expect(loadedUrls).toEqual(["http://127.0.0.1:8000"]);
  });

  it("defaults the desktop shell chrome to the light workbench theme", () => {
    expect(mainSource).toContain('nativeTheme.themeSource = "light"');
  });
});
