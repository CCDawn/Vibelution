import { app, ipcMain, nativeTheme } from "electron";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { singleInstanceDecision } from "./appLock.js";
import { applyDesktopCliToEnvironment, parseDesktopCliArgs } from "./cli/desktopCli.js";
import { IPC_CHANNELS } from "./ipc.js";
import {
  DESKTOP_LAUNCH_PROFILE_FILE,
  applyDesktopLaunchSettingsToEnvironment,
  resolveDesktopLaunchSettings,
  type DesktopLaunchSettings
} from "./launch/desktopLaunchSettings.js";
import { RuntimeSceneBridge, type RuntimeSceneElectronEvent } from "./lifecycle/runtimeSceneBridge.js";
import { createDesktopPaths, resolveDesktopEntryCatalogPath, type DesktopPaths } from "./paths.js";
import { fetchLauncherControlToken, runDesktopActionOnce } from "./protocol/desktopActionClient.js";
import { findVibelutionDeepLinkArg, parsePublicVibelutionDeepLink } from "./protocol/deepLink.js";
import {
  buildDeepLinkRegistrationPlan,
  readDesktopEntryCatalog,
  registerDeepLinkProtocolIfAllowed,
  skippedDeepLinkRegistration,
  type DeepLinkRegistrationResult
} from "./protocol/deepLinkRegistration.js";
import {
  bootstrapPythonLauncherService,
  stopPythonLauncherService,
  type LauncherServiceStopResult
} from "./process/launcherServiceClient.js";
import type { LauncherBootstrapResult } from "./process/launcherBootstrap.js";
import { assertTrustedIpcSender } from "./security/ipcSenderValidation.js";
import { executeApprovedDesktopShellShutdown } from "./shutdown/desktopShellExit.js";
import { decideShutdown, fetchLauncherActiveWorkStatus, type ShutdownDecision } from "./shutdown/shutdownCoordinator.js";
import {
  desktopSmokeSummary,
  desktopSmokeSummaryPath,
  emptyDesktopSmokeBootstrapSummary,
  type DesktopSmokeBootstrapSummary
} from "./smoke/desktopSmoke.js";
import { prepareDesktopSmokeShutdown } from "./smoke/desktopSmokeShutdown.js";
import { closeDesktopSession, registerDesktopSession, reportDesktopWindowState } from "./windows/desktopSessionClient.js";
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import type { ManagedWindowState } from "./windows/windowProviderTypes.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import { resolveLauncherUrl, resolveWorkbenchUrl } from "./windows/windowUrlResolver.js";

const DESKTOP_ACTION_POLL_MS = 2000;
const DESKTOP_ACTION_LEASE_SECONDS = 30;
const RUNTIME_SCENE_MAX_BUFFERED_EVENTS = 50;

let windowProvider: ElectronWindowProvider | null = null;
let launcherBootstrap: LauncherBootstrapResult | null = null;
let desktopActionTimer: ReturnType<typeof setInterval> | null = null;
let desktopActionPollRunning = false;
let desktopActionContext: DesktopActionLoopContext | null = null;
let runtimeSceneBridge: RuntimeSceneBridge | null = null;
let desktopSessionRegistered = false;
let desktopSessionRevision = 0;
let shutdownApproved = false;
let shutdownRequestRunning = false;
const desktopCliArgs = parseDesktopCliArgs(process.argv.slice(1));
let cachedDesktopLaunchSettings: DesktopLaunchSettings | null = null;

type DesktopActionLoopContext = {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
};

type PublicDeepLinkSource = "open_url" | "second_instance" | "startup";

type PendingPublicDeepLink = {
  rawUrl: string;
  source: PublicDeepLinkSource;
};

const pendingPublicDeepLinks: PendingPublicDeepLink[] = [];
const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock());
nativeTheme.themeSource = "light";
if (!desktopCliArgs.smoke && lockDecision.action === "focus_existing") {
  app.quit();
}

function createDesktopPathsForApp(): DesktopPaths {
  const launchSettings = desktopLaunchSettings();
  const workspaceRoot = desktopEnvironment().VIBELUTION_WORKSPACE_ROOT;
  if (!workspaceRoot) {
    const profileHint = [
      `Provide --workspace, VIBELUTION_WORKSPACE_ROOT, or ${DESKTOP_LAUNCH_PROFILE_FILE}.`,
      `Searched: ${launchSettings.searchedProfilePaths.join("; ") || "none"}.`,
      launchSettings.profileError ? `Profile warning: ${launchSettings.profileError}.` : ""
    ]
      .filter(Boolean)
      .join(" ");
    throw new Error(`VIBELUTION_WORKSPACE_ROOT is required until the first-run workspace picker exists. ${profileHint}`);
  }
  const paths = createDesktopPaths({
    importMetaUrl: import.meta.url,
    resourcesRoot: process.resourcesPath,
    userDataRoot: app.getPath("userData"),
    workspaceRoot
  });
  return paths;
}

function registerPackagedDeepLinks(paths: DesktopPaths): DeepLinkRegistrationResult {
  try {
    const catalog = readDesktopEntryCatalog(resolveDesktopEntryCatalogPath(paths));
    const plan = buildDeepLinkRegistrationPlan(catalog, {
      platform: process.platform,
      executablePath: process.execPath
    });
    return registerDeepLinkProtocolIfAllowed(plan, {
      app,
      env: desktopEnvironment(),
      platform: process.platform,
      smoke: desktopCliArgs.smoke
    });
  } catch {
    return skippedDeepLinkRegistration({ protocol: "vibelution" }, "catalog_unavailable");
  }
}

function desktopLaunchSettings(): DesktopLaunchSettings {
  if (cachedDesktopLaunchSettings !== null) {
    return cachedDesktopLaunchSettings;
  }
  cachedDesktopLaunchSettings = resolveDesktopLaunchSettings({
    env: process.env,
    cliArgs: desktopCliArgs,
    resourcesRoot: process.resourcesPath,
    userDataRoot: app.getPath("userData")
  });
  return cachedDesktopLaunchSettings;
}

function desktopEnvironment(): NodeJS.ProcessEnv {
  const baseEnv = {
    ...process.env,
    NODE_ENV: process.env.NODE_ENV || (app.isPackaged ? "production" : "development")
  };
  return applyDesktopLaunchSettingsToEnvironment(applyDesktopCliToEnvironment(baseEnv, desktopCliArgs), desktopLaunchSettings());
}

function createWindowProvider(paths: DesktopPaths, bootstrap: LauncherBootstrapResult | null): ElectronWindowProvider {
  const desktopEnv = desktopEnvironment();
  return new ElectronWindowProvider(
    paths,
    resolveLauncherUrl(desktopEnv, bootstrap?.launcherUrl),
    resolveWorkbenchUrl(desktopEnv, bootstrap?.workbenchUrl),
    {
      createLauncherWindow,
      createWorkbenchWindow,
      reportState: (state) => reportManagedWindowState(paths, bootstrap, state),
      shouldInterceptLauncherClose: () => !shutdownApproved,
      onLauncherCloseRequest: () => {
        void requestDesktopShellExit().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      }
    }
  );
}

async function bootstrapLauncherIfEnabled(paths: DesktopPaths): Promise<LauncherBootstrapResult | null> {
  const desktopEnv = desktopEnvironment();
  if (desktopEnv.VIBELUTION_ELECTRON_START_LAUNCHER === "0") {
    return null;
  }
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
      const result = await runDesktopActionOnce({
        ...context,
        leaseSeconds: DESKTOP_ACTION_LEASE_SECONDS,
        operations: {
          openOrFocusWorkbench: () => provider.openOrFocusWorkbench(),
          focusWorkbench: () => provider.focusWorkbench(),
          closeWorkbench: () => provider.closeWorkbench()
        }
      });
      if (result.claimed) {
        await recordElectronSupervisorEvent(bootstrap, {
          eventCode: "electron.desktop_action.claimed",
          message: "Desktop action claimed.",
          fields: { actionId: result.actionId, action: result.action, desktopSessionId: context.desktopSessionId }
        });
        await recordElectronSupervisorEvent(bootstrap, {
          eventCode: result.status === "acked" ? "electron.desktop_action.succeeded" : "electron.desktop_action.failed",
          message: `Desktop action ${result.status}.`,
          fields: { actionId: result.actionId, action: result.action, desktopSessionId: context.desktopSessionId }
        });
        if (result.action === "open_workbench" && result.status === "acked") {
          await recordElectronSupervisorEvent(bootstrap, {
            eventCode: "electron.workbench.window.opened",
            message: "Workbench window opened by Electron.",
            fields: { desktopSessionId: context.desktopSessionId }
          });
        }
      }
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    } finally {
      desktopActionPollRunning = false;
    }
  };

  void pollOnce();
  desktopActionTimer = setInterval(() => void pollOnce(), DESKTOP_ACTION_POLL_MS);
}

async function reportManagedWindowState(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  state: ManagedWindowState
): Promise<void> {
  if (bootstrap === null) {
    return;
  }
  try {
    const context = await resolveDesktopActionLoopContext(bootstrap);
    if (!desktopSessionRegistered) {
      const registration = await registerDesktopSession({
        ...context,
        workspaceRoot: paths.workspaceRoot,
        capabilities: bootstrap.capabilities
      });
      desktopSessionRevision = registration.revision;
      desktopSessionRegistered = true;
    }
    const result = await reportDesktopWindowState({
      ...context,
      role: state.role,
      revision: desktopSessionRevision,
      state
    });
    desktopSessionRevision = result.revision;
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

async function resolveDesktopActionLoopContext(bootstrap: LauncherBootstrapResult): Promise<DesktopActionLoopContext> {
  if (desktopActionContext !== null) {
    return desktopActionContext;
  }
  const desktopEnv = desktopEnvironment();
  const launcherOrigin = resolveLauncherUrl(desktopEnv, bootstrap.launcherUrl);
  const envToken = String(desktopEnv.VIBELUTION_WEB_CONTROL_TOKEN || "").trim();
  const controlToken = envToken || (await fetchLauncherControlToken({ launcherOrigin }));
  desktopActionContext = {
    launcherOrigin,
    controlToken,
    desktopSessionId: currentDesktopSessionId(bootstrap, desktopEnv)
  };
  return desktopActionContext;
}

async function resolveRuntimeSceneBridge(bootstrap: LauncherBootstrapResult): Promise<RuntimeSceneBridge> {
  if (runtimeSceneBridge !== null) {
    return runtimeSceneBridge;
  }
  const context = await resolveDesktopActionLoopContext(bootstrap);
  runtimeSceneBridge = new RuntimeSceneBridge({
    launcherOrigin: context.launcherOrigin,
    controlToken: context.controlToken,
    maxBufferedEvents: RUNTIME_SCENE_MAX_BUFFERED_EVENTS
  });
  return runtimeSceneBridge;
}

async function recordElectronSupervisorEvent(
  bootstrap: LauncherBootstrapResult | null,
  event: RuntimeSceneElectronEvent
): Promise<void> {
  if (bootstrap === null) {
    return;
  }
  try {
    const bridge = await resolveRuntimeSceneBridge(bootstrap);
    await bridge.record(event);
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

async function handlePublicDeepLinkUrl(rawUrl: string, source: PublicDeepLinkSource): Promise<void> {
  if (windowProvider === null) {
    pendingPublicDeepLinks.push({ rawUrl, source });
    return;
  }

  try {
    const link = parsePublicVibelutionDeepLink(rawUrl);
    if (link.kind === "focus_launcher") {
      await windowProvider.openLauncher();
    }
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.deep_link.accepted",
      message: "Electron public deep link accepted.",
      fields: { source, action: link.kind }
    });
  } catch (error: unknown) {
    await windowProvider.openLauncher();
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.deep_link.rejected",
      message: "Electron public deep link rejected.",
      fields: {
        source,
        reason: error instanceof Error ? error.message : String(error)
      }
    });
  }
}

async function flushPendingPublicDeepLinks(): Promise<void> {
  const pending = pendingPublicDeepLinks.splice(0);
  for (const item of pending) {
    await handlePublicDeepLinkUrl(item.rawUrl, item.source);
  }
}

function currentDesktopSessionId(
  bootstrap: LauncherBootstrapResult | null,
  desktopEnv: NodeJS.ProcessEnv = desktopEnvironment()
): string {
  const envDesktopSessionId = String(desktopEnv.VIBELUTION_DESKTOP_SESSION_ID || "").trim();
  if (envDesktopSessionId) {
    return envDesktopSessionId;
  }
  if (desktopActionContext?.desktopSessionId) {
    return desktopActionContext.desktopSessionId;
  }
  if (bootstrap === null) {
    return "";
  }
  const bootstrapId = String(bootstrap.launcherInstanceId || bootstrap.workspaceId || process.pid).trim();
  return `electron-${bootstrapId}`;
}

function stopDesktopActionLoop(): void {
  if (desktopActionTimer !== null) {
    clearInterval(desktopActionTimer);
    desktopActionTimer = null;
  }
  desktopActionPollRunning = false;
}

async function closeDesktopSessionIfRegistered(): Promise<void> {
  if (!desktopSessionRegistered || launcherBootstrap === null) {
    return;
  }
  try {
    await closeDesktopSession(await resolveDesktopActionLoopContext(launcherBootstrap));
    desktopSessionRegistered = false;
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

async function stopOwnedPythonLauncherService(): Promise<LauncherServiceStopResult> {
  if (launcherBootstrap === null || launcherBootstrap.launcherBackendPid <= 0) {
    return {
      schemaVersion: 1,
      status: "skipped",
      reason: "missing_owned_launcher_backend_pid",
      expectedBackendPid: 0,
      launcherBackendPid: launcherBootstrap?.launcherBackendPid ?? 0,
      terminatedPids: []
    };
  }
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to stop the owned Launcher Service");
  }
  return await stopPythonLauncherService({
    workspaceRoot: launcherBootstrap.workspaceRoot,
    pythonPath,
    operatorConfigPath: launcherBootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    launcherBackendPid: launcherBootstrap.launcherBackendPid
  });
}

async function runSmokeAndQuit(paths: DesktopPaths): Promise<void> {
  const desktopEnv = desktopEnvironment();
  const bootstrap = await resolveSmokeBootstrap(paths, desktopEnv);
  launcherBootstrap = bootstrap.result;
  const launcherUrl = bootstrap.launcherUrl || String(desktopEnv.VIBELUTION_LAUNCHER_URL || "http://127.0.0.1:8765/launcher");
  const workbenchUrl = bootstrap.workbenchUrl || String(desktopEnv.VIBELUTION_WORKBENCH_URL || "http://127.0.0.1:8000/");
  const controlToken = String(desktopEnv.VIBELUTION_WEB_CONTROL_TOKEN || "");
  const shutdown = await prepareDesktopSmokeShutdown({
    bootstrap: bootstrap.result,
    closeDesktopSession: closeDesktopSessionIfRegistered,
    recordEvent: async (event) => {
      await recordElectronSupervisorEvent(launcherBootstrap, {
        ...event,
        fields: {
          ownershipMode: launcherBootstrap?.mode ?? "attached",
          ...(event.fields ?? {})
        }
      });
    },
    stopPythonLauncher: stopOwnedPythonLauncherService,
    approveShutdown: () => {
      shutdownApproved = true;
    },
    stopDesktopActionLoop
  });
  const summary = desktopSmokeSummary({
    workspaceRoot: paths.workspaceRoot,
    configPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || ""),
    launcherUrl,
    workbenchUrl,
    controlToken,
    packaged: app.isPackaged,
    bootstrap: bootstrap.summary,
    shutdown
  });
  const summaryPath = desktopSmokeSummaryPath(paths.workspaceRoot);
  mkdirSync(dirname(summaryPath), { recursive: true });
  writeFileSync(summaryPath, JSON.stringify(summary, null, 2), "utf-8");
  console.log(JSON.stringify(summary, null, 2));
  if (bootstrap.summary.attempted && !bootstrap.summary.parsed) {
    process.exitCode = 1;
  }
  if (!shutdownApproved) {
    shutdownApproved = true;
  }
  app.quit();
}

async function resolveSmokeBootstrap(
  paths: DesktopPaths,
  desktopEnv: NodeJS.ProcessEnv
): Promise<{
  summary: DesktopSmokeBootstrapSummary;
  result: LauncherBootstrapResult | null;
  launcherUrl: string;
  workbenchUrl: string;
}> {
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  const bootstrapRequested = String(desktopEnv.VIBELUTION_ELECTRON_SMOKE_BOOTSTRAP || "").trim() === "1";
  const shouldAttempt = bootstrapRequested || Boolean(pythonPath);
  if (!shouldAttempt) {
    return { summary: emptySmokeBootstrapSummary({ attempted: false }), result: null, launcherUrl: "", workbenchUrl: "" };
  }
  try {
    const result = await bootstrapLauncherIfEnabled(paths);
    if (result === null) {
      return { summary: emptySmokeBootstrapSummary({ attempted: true }), result: null, launcherUrl: "", workbenchUrl: "" };
    }
    return {
      summary: {
        attempted: true,
        parsed: true,
        mode: result.mode,
        launcherBackendPid: result.launcherBackendPid,
        protocolVersion: result.protocolVersion,
        capabilities: [...result.capabilities].sort(),
        launcherOrigin: safeOrigin(result.launcherUrl),
        workbenchOrigin: safeOrigin(result.workbenchUrl),
        errorType: "",
        errorMessage: ""
      },
      result,
      launcherUrl: result.launcherUrl,
      workbenchUrl: result.workbenchUrl
    };
  } catch (error: unknown) {
    return {
      summary: emptySmokeBootstrapSummary({
        attempted: true,
        errorType: error instanceof Error ? error.name : "Error",
        errorMessage: (error instanceof Error ? error.message : String(error)).slice(0, 500)
        }),
      result: null,
      launcherUrl: "",
      workbenchUrl: ""
    };
  }
}

function emptySmokeBootstrapSummary(
  overrides: Partial<DesktopSmokeBootstrapSummary> = {}
): DesktopSmokeBootstrapSummary {
  return { ...emptyDesktopSmokeBootstrapSummary(), ...overrides };
}

function safeOrigin(value: string): string {
  try {
    return new URL(value).origin;
  } catch {
    return "";
  }
}

function trustedIpcOrigins(): string[] {
  const desktopEnv = desktopEnvironment();
  return Array.from(
    new Set([
      new URL(resolveLauncherUrl(desktopEnv, launcherBootstrap?.launcherUrl)).origin,
      new URL(resolveWorkbenchUrl(desktopEnv, launcherBootstrap?.workbenchUrl)).origin
    ])
  );
}

async function requestDesktopShellExit(): Promise<ShutdownDecision> {
  if (shutdownRequestRunning) {
    return { allowed: false, reason: "active_work_running", message: "Desktop shell exit is already being evaluated." };
  }
  shutdownRequestRunning = true;
  try {
    const decision = await decideShutdown({
      ownershipMode: launcherBootstrap?.mode ?? "attached",
      activeWorkStatus: async () => {
        if (launcherBootstrap === null) {
          return { active: false, message: "" };
        }
        const context = await resolveDesktopActionLoopContext(launcherBootstrap);
        return fetchLauncherActiveWorkStatus(context);
      }
    });
    if (decision.allowed) {
      await executeApprovedDesktopShellShutdown({
        decision,
        closeDesktopSession: closeDesktopSessionIfRegistered,
        recordEvent: async (event) => {
          await recordElectronSupervisorEvent(launcherBootstrap, {
            ...event,
            fields: {
              ownershipMode: launcherBootstrap?.mode ?? "attached",
              ...(event.fields ?? {})
            }
          });
        },
        stopPythonLauncher: stopOwnedPythonLauncherService,
        approveShutdown: () => {
          shutdownApproved = true;
        },
        stopDesktopActionLoop,
        quitApp: () => {
          app.quit();
        }
      });
    }
    return decision;
  } finally {
    shutdownRequestRunning = false;
  }
}

ipcMain.handle(IPC_CHANNELS.getVersion, (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return app.getVersion();
});

ipcMain.handle(IPC_CHANNELS.getDesktopShellSummary, (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return {
    schemaVersion: 1,
    provider: "electron",
    desktopSessionId: currentDesktopSessionId(launcherBootstrap),
    windows: windowProvider?.snapshot() ?? null,
    bootstrap: launcherBootstrap
      ? {
          mode: launcherBootstrap.mode,
          launcherBackendPid: launcherBootstrap.launcherBackendPid,
          protocolVersion: launcherBootstrap.protocolVersion,
          minDesktopProtocolVersion: launcherBootstrap.minDesktopProtocolVersion,
          maxDesktopProtocolVersion: launcherBootstrap.maxDesktopProtocolVersion,
          capabilities: launcherBootstrap.capabilities
        }
      : null
  };
});

ipcMain.handle(IPC_CHANNELS.focusWorkbenchWindow, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return await windowProvider?.focusWorkbench();
});

ipcMain.handle(IPC_CHANNELS.requestDesktopShellExit, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return await requestDesktopShellExit();
});

app.whenReady()
  .then(async () => {
    const paths = createDesktopPathsForApp();
    if (desktopCliArgs.smoke) {
      await runSmokeAndQuit(paths);
      return;
    }
    const deepLinkRegistration = registerPackagedDeepLinks(paths);
    launcherBootstrap = await bootstrapLauncherIfEnabled(paths);
    windowProvider = createWindowProvider(paths, launcherBootstrap);
    await windowProvider.openLauncher();
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.launcher.supervisor.started",
      message: "Electron launcher supervisor started.",
      fields: {
        provider: "electron",
        deepLinkRegistrationAttempted: deepLinkRegistration.attempted,
        deepLinkRegistrationRegistered: deepLinkRegistration.registered,
        deepLinkRegistrationReason: deepLinkRegistration.reason
      }
    });
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.launcher_service.started",
      message: "Python launcher service is attached to Electron.",
      fields: {
        mode: launcherBootstrap?.mode ?? "",
        launcherBackendPid: launcherBootstrap?.launcherBackendPid ?? 0
      }
    });
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.launcher.window.opened",
      message: "Launcher window opened by Electron.",
      fields: { provider: "electron" }
    });
    const rawUrl = findVibelutionDeepLinkArg(process.argv.slice(1));
    if (rawUrl) {
      await handlePublicDeepLinkUrl(rawUrl, "startup");
    }
    await flushPendingPublicDeepLinks();
    startDesktopActionLoop(launcherBootstrap, windowProvider);
  })
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    app.quit();
  });

app.on("second-instance", (_event, argv) => {
  const rawUrl = findVibelutionDeepLinkArg(argv);
  if (rawUrl) {
    void handlePublicDeepLinkUrl(rawUrl, "second_instance");
    return;
  }
  void windowProvider?.openLauncher();
});

app.on("open-url", (event, rawUrl) => {
  event.preventDefault();
  void handlePublicDeepLinkUrl(rawUrl, "open_url");
});

app.on("before-quit", (event) => {
  if (shutdownApproved) {
    stopDesktopActionLoop();
    return;
  }
  event.preventDefault();
  void requestDesktopShellExit().catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
});

app.on("window-all-closed", () => {
  void requestDesktopShellExit().catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
});
