import { app, BrowserWindow, ipcMain } from "electron";
import { createDesktopPaths, resolvePreloadPath } from "./paths.js";

let launcherWindow: BrowserWindow | null = null;

function createLauncherWindow(): BrowserWindow {
  const workspaceRoot = process.env.VIBELUTION_WORKSPACE_ROOT;
  if (!workspaceRoot) {
    throw new Error("VIBELUTION_WORKSPACE_ROOT is required until the first-run workspace picker exists");
  }
  const paths = createDesktopPaths({
    importMetaUrl: import.meta.url,
    resourcesRoot: process.resourcesPath,
    userDataRoot: app.getPath("userData"),
    workspaceRoot
  });
  const window = new BrowserWindow({
    width: 1180,
    height: 760,
    title: "Vibelution Launcher",
    webPreferences: {
      preload: resolvePreloadPath(paths),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });
  void window.loadURL("about:blank");
  return window;
}

ipcMain.handle("launcher:get-version", () => app.getVersion());

app.whenReady().then(() => {
  launcherWindow = createLauncherWindow();
  launcherWindow.on("closed", () => {
    launcherWindow = null;
  });
});

app.on("window-all-closed", () => {
  // Task 11 replaces this with ShutdownCoordinator; scaffold must not bypass active-work guard.
});
