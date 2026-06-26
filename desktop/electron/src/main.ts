import { app, ipcMain } from "electron";
import { singleInstanceDecision } from "./appLock.js";
import { createDesktopPaths, type DesktopPaths } from "./paths.js";
import { bootstrapPythonLauncherService } from "./process/launcherServiceClient.js";
import type { LauncherBootstrapResult } from "./process/launcherBootstrap.js";
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import { resolveLauncherUrl, resolveWorkbenchUrl } from "./windows/windowUrlResolver.js";

let windowProvider: ElectronWindowProvider | null = null;
let launcherBootstrap: LauncherBootstrapResult | null = null;

const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock());
if (lockDecision.action === "focus_existing") {
  app.quit();
}

function createDesktopPathsForApp(): DesktopPaths {
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
  return paths;
}

function desktopEnvironment(): NodeJS.ProcessEnv {
  return {
    ...process.env,
    NODE_ENV: process.env.NODE_ENV || (app.isPackaged ? "production" : "development")
  };
}

function createWindowProvider(paths: DesktopPaths, bootstrap: LauncherBootstrapResult | null): ElectronWindowProvider {
  const desktopEnv = desktopEnvironment();
  return new ElectronWindowProvider(
    paths,
    resolveLauncherUrl(desktopEnv, bootstrap?.launcherUrl),
    resolveWorkbenchUrl(desktopEnv, bootstrap?.workbenchUrl),
    { createLauncherWindow, createWorkbenchWindow }
  );
}

async function bootstrapLauncherIfEnabled(paths: DesktopPaths): Promise<LauncherBootstrapResult | null> {
  if (process.env.VIBELUTION_ELECTRON_START_LAUNCHER === "0") {
    return null;
  }
  const desktopEnv: NodeJS.ProcessEnv = {
    ...process.env,
    NODE_ENV: process.env.NODE_ENV || (app.isPackaged ? "production" : "development")
  };
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to bootstrap the Launcher Service");
  }
  return await bootstrapPythonLauncherService({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    operatorConfigPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim()
  });
}

ipcMain.handle("launcher:get-version", () => app.getVersion());

app.whenReady()
  .then(async () => {
    const paths = createDesktopPathsForApp();
    launcherBootstrap = await bootstrapLauncherIfEnabled(paths);
    windowProvider = createWindowProvider(paths, launcherBootstrap);
    await windowProvider.openLauncher();
  })
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    app.quit();
  });

app.on("second-instance", () => {
  void windowProvider?.openLauncher();
});

app.on("window-all-closed", () => {
  // Task 11 replaces this with ShutdownCoordinator; scaffold must not bypass active-work guard.
});
