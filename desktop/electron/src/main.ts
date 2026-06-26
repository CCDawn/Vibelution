import { app, ipcMain } from "electron";
import { singleInstanceDecision } from "./appLock.js";
import { createDesktopPaths, resolvePreloadPath } from "./paths.js";
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import { resolveLauncherUrl, resolveWorkbenchUrl } from "./windows/windowUrlResolver.js";

let windowProvider: ElectronWindowProvider | null = null;

const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock());
if (lockDecision.action === "focus_existing") {
  app.quit();
}

function createWindowProvider(): ElectronWindowProvider {
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
  const desktopEnv: NodeJS.ProcessEnv = {
    ...process.env,
    NODE_ENV: process.env.NODE_ENV || (app.isPackaged ? "production" : "development")
  };
  return new ElectronWindowProvider(
    paths,
    resolveLauncherUrl(desktopEnv),
    resolveWorkbenchUrl(desktopEnv),
    { createLauncherWindow, createWorkbenchWindow }
  );
}

ipcMain.handle("launcher:get-version", () => app.getVersion());

app.whenReady().then(() => {
  windowProvider = createWindowProvider();
  void windowProvider.openLauncher();
});

app.on("second-instance", () => {
  void windowProvider?.openLauncher();
});

app.on("window-all-closed", () => {
  // Task 11 replaces this with ShutdownCoordinator; scaffold must not bypass active-work guard.
});
