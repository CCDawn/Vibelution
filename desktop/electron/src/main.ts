import { app, ipcMain } from "electron";
import { singleInstanceDecision } from "./appLock.js";
import { createDesktopPaths, type DesktopPaths } from "./paths.js";
import { fetchLauncherControlToken, runDesktopActionOnce } from "./protocol/desktopActionClient.js";
import { bootstrapPythonLauncherService } from "./process/launcherServiceClient.js";
import type { LauncherBootstrapResult } from "./process/launcherBootstrap.js";
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import { resolveLauncherUrl, resolveWorkbenchUrl } from "./windows/windowUrlResolver.js";

const DESKTOP_ACTION_POLL_MS = 2000;
const DESKTOP_ACTION_LEASE_SECONDS = 30;

let windowProvider: ElectronWindowProvider | null = null;
let launcherBootstrap: LauncherBootstrapResult | null = null;
let desktopActionTimer: ReturnType<typeof setInterval> | null = null;
let desktopActionPollRunning = false;
let desktopActionContext: DesktopActionLoopContext | null = null;

type DesktopActionLoopContext = {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
};

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

function startDesktopActionLoop(bootstrap: LauncherBootstrapResult | null, provider: ElectronWindowProvider): void {
  if (bootstrap === null || desktopActionTimer !== null) {
    return;
  }

  const pollOnce = async () => {
    if (desktopActionPollRunning) {
      return;
    }
    desktopActionPollRunning = true;
    try {
      const context = await resolveDesktopActionLoopContext(bootstrap);
      await runDesktopActionOnce({
        ...context,
        leaseSeconds: DESKTOP_ACTION_LEASE_SECONDS,
        operations: {
          openOrFocusWorkbench: () => provider.openOrFocusWorkbench(),
          focusWorkbench: () => provider.focusWorkbench(),
          closeWorkbench: () => provider.closeWorkbench()
        }
      });
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    } finally {
      desktopActionPollRunning = false;
    }
  };

  void pollOnce();
  desktopActionTimer = setInterval(() => void pollOnce(), DESKTOP_ACTION_POLL_MS);
}

async function resolveDesktopActionLoopContext(bootstrap: LauncherBootstrapResult): Promise<DesktopActionLoopContext> {
  if (desktopActionContext !== null) {
    return desktopActionContext;
  }
  const desktopEnv = desktopEnvironment();
  const launcherOrigin = resolveLauncherUrl(desktopEnv, bootstrap.launcherUrl);
  const envToken = String(desktopEnv.VIBELUTION_WEB_CONTROL_TOKEN || "").trim();
  const controlToken = envToken || (await fetchLauncherControlToken({ launcherOrigin }));
  const envDesktopSessionId = String(desktopEnv.VIBELUTION_DESKTOP_SESSION_ID || "").trim();
  const bootstrapId = String(bootstrap.launcherInstanceId || bootstrap.workspaceId || process.pid).trim();
  desktopActionContext = {
    launcherOrigin,
    controlToken,
    desktopSessionId: envDesktopSessionId || `electron-${bootstrapId}`
  };
  return desktopActionContext;
}

function stopDesktopActionLoop(): void {
  if (desktopActionTimer !== null) {
    clearInterval(desktopActionTimer);
    desktopActionTimer = null;
  }
  desktopActionPollRunning = false;
}

ipcMain.handle("launcher:get-version", () => app.getVersion());

app.whenReady()
  .then(async () => {
    const paths = createDesktopPathsForApp();
    launcherBootstrap = await bootstrapLauncherIfEnabled(paths);
    windowProvider = createWindowProvider(paths, launcherBootstrap);
    await windowProvider.openLauncher();
    startDesktopActionLoop(launcherBootstrap, windowProvider);
  })
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    app.quit();
  });

app.on("second-instance", () => {
  void windowProvider?.openLauncher();
});

app.on("before-quit", () => {
  stopDesktopActionLoop();
});

app.on("window-all-closed", () => {
  // Task 11 replaces this with ShutdownCoordinator; scaffold must not bypass active-work guard.
});
