import { BrowserWindow, Notification, app, dialog, ipcMain, nativeImage, nativeTheme, protocol } from "electron";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import {
  pinSharedDesktopShellUserData,
  resolveSecondInstanceIntent,
  singleInstanceDecision
} from "./appLock.js";
import { applyDesktopCliToEnvironment, parseDesktopCliArgs } from "./cli/desktopCli.js";
import { IPC_CHANNELS } from "./ipc.js";
import {
  DESKTOP_LAUNCH_PROFILE_FILE,
  applyDesktopLaunchSettingsToEnvironment,
  resolveDesktopLaunchSettings,
  type DesktopLaunchSettings
} from "./launch/desktopLaunchSettings.js";
import { RuntimeSceneBridge, type RuntimeSceneElectronEvent } from "./lifecycle/runtimeSceneBridge.js";
import {
  DesktopLifecycleCoordinator,
  DesktopSessionMutationQueue,
  type DesktopCloseReason
} from "./lifecycle/desktopLifecycleCoordinator.js";
import { isWorkbenchCloseControlFetchFailure } from "./lifecycle/workbenchCloseFailOpen.js";
import {
  createConversationNotificationService,
  type ConversationNotificationService,
  type DesktopConversationCompletionNotification,
  type DesktopConversationNotificationResult
} from "./notifications/conversationNotifications.js";
import { createDesktopPaths, resolveDesktopEntryCatalogPath, type DesktopPaths } from "./paths.js";
import { fetchLauncherControlToken, runDesktopActionOnce } from "./protocol/desktopActionClient.js";
import { applyProjectSlot } from "./protocol/applyProjectSlot.js";
import {
  fetchLauncherBranchInstances,
  fetchLauncherFreshness,
  fetchLauncherStatusSummary,
  formatLauncherStatusSummary,
  postLauncherControl,
  type LauncherControlPostPath
} from "./protocol/launcherControlClient.js";
import {
  createLauncherIpcHost,
  type LauncherIpcInvokePayload,
  type OrchestratedBranchInstanceResult,
  type OrchestratedLifecycleResult
} from "./protocol/launcherIpcHost.js";
import {
  LAUNCHER_APP_PROTOCOL,
  launcherAppOriginFor,
  registerLauncherAppProtocolHandle,
  resolveLauncherDistRoot
} from "./protocol/launcherAppProtocol.js";
import {
  isRecoverableWorkbenchCloseTransactionControlRejection
} from "./protocol/workbenchCloseTransactionClient.js";
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
import {
  runWorkbenchLifecycle,
  type WorkbenchLifecycleOperation
} from "./process/workbenchLifecycle.js";
import {
  runBranchInstanceBridge,
  type BranchInstanceOperation
} from "./process/branchInstanceBridge.js";
import { runPythonJsonBridge } from "./process/pythonJsonBridge.js";
import {
  completeBootstrapWithoutWaitingForTelemetry,
  drainTelemetryWithDeadline,
  scheduleTelemetryWithoutWaiting,
  type LauncherBootstrapResult
} from "./process/launcherBootstrap.js";
import { assertTrustedIpcSender } from "./security/ipcSenderValidation.js";
import { executeApprovedDesktopShellShutdown, DESKTOP_SHELL_EXIT_BUDGET_MS, DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS, withDesktopShellExitTimeout } from "./shutdown/desktopShellExit.js";
import {
  decideShutdown,
  executeShutdownAuthorizationBoundary,
  fetchLauncherActiveWorkStatus,
  type ShutdownDecision
} from "./shutdown/shutdownCoordinator.js";
import {
  desktopSmokeSummary,
  desktopSmokeSummaryPath,
  emptyDesktopSmokeBootstrapSummary,
  type DesktopSmokeBootstrapSummary
} from "./smoke/desktopSmoke.js";
import {
  desktopWorkbenchCloseCanarySummary,
  desktopWorkbenchCloseCanarySummaryPath
} from "./smoke/workbenchCloseCanary.js";
import { prepareDesktopSmokeShutdown } from "./smoke/desktopSmokeShutdown.js";
import { createDesktopTray, DESKTOP_TRAY_MENU_LABELS } from "./tray/desktopTray.js";
import {
  claimElectronDesktopShellOwner,
  releaseElectronDesktopShellOwner
} from "./tray/desktopShellOwner.js";
import {
  closeDesktopSession,
  heartbeatDesktopSession,
  registerDesktopSession,
  reportDesktopWindowState
} from "./windows/desktopSessionClient.js";
import { InProcessDesktopSessionStore } from "./windows/desktopSessionStore.js";
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import type { ManagedWindowState } from "./windows/windowProviderTypes.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import {
  resolveLauncherControlPlaneUrl,
  resolveLauncherWindowUrl,
  resolveWorkbenchUrl
} from "./windows/windowUrlResolver.js";
import { installBrokenPipeGuards } from "./runtime/brokenPipeGuard.js";
import { MainWorkbenchCloseTransactionStore } from "./lifecycle/workbenchCloseTransactionStore.js";

installBrokenPipeGuards();

protocol.registerSchemesAsPrivileged([
  {
    scheme: LAUNCHER_APP_PROTOCOL,
    privileges: { standard: true, secure: true, supportFetchAPI: true }
  }
]);

const DESKTOP_ACTION_POLL_MS = 2000;
const DESKTOP_ACTION_WAIT_MS = 1750;
const DESKTOP_ACTION_LEASE_SECONDS = 30;
const RUNTIME_SCENE_MAX_BUFFERED_EVENTS = 50;
const DESKTOP_SESSION_HEARTBEAT_MS = 15000;
const DESKTOP_SESSIONS_HEARTBEAT_CAPABILITY = "desktop_sessions.heartbeat";
const WORKBENCH_CLOSE_TRANSACTION_CAPABILITY = "workbench_close.transaction.v1";
const DESKTOP_SESSION_GENERATION = `${process.pid}-${Date.now().toString(36)}`;
const WORKBENCH_CLOSE_AUTHORIZATION_MAX_WAIT_MS = 30_000;
const ACTIVE_WORK_STATUS_TIMEOUT_MS = DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS;
const ELECTRON_PROCESS_STARTED_AT_MS = performance.now();
const ELECTRON_STARTUP_TRACE_ID = String(process.env.VIBELUTION_STARTUP_TRACE_ID || "").trim().slice(0, 96);

let windowProvider: ElectronWindowProvider | null = null;
let launcherBootstrap: LauncherBootstrapResult | null = null;
let desktopActionTimer: ReturnType<typeof setInterval> | null = null;
let desktopActionPollRunning = false;
let desktopSessionHeartbeatTimer: ReturnType<typeof setInterval> | null = null;
let desktopSessionHeartbeatRunning = false;
let desktopActionContext: DesktopActionLoopContext | null = null;
let runtimeSceneBridge: RuntimeSceneBridge | null = null;
let desktopTray: ReturnType<typeof createDesktopTray> | null = null;
let currentWorkbenchUrl = "";
let desktopSessionRegistered = false;
let desktopSessionRevision = 0;
let desktopControlRecoveryPromise: Promise<void> | null = null;
let shutdownApproved = false;
let launcherIpcHost: ReturnType<typeof createLauncherIpcHost> | null = null;
const inProcessDesktopSessionStore = new InProcessDesktopSessionStore();
const mainWorkbenchCloseStore = new MainWorkbenchCloseTransactionStore();
const WORKBENCH_CLOSE_BACKEND_WAIT_MS = 30_000;
const desktopLifecycleCoordinator = new DesktopLifecycleCoordinator();
const desktopSessionMutations = new DesktopSessionMutationQueue();
let conversationNotificationService: ConversationNotificationService | null = null;
const desktopCliArgs = parseDesktopCliArgs(process.argv.slice(1));
let pendingOpenWorkbenchRequest = desktopCliArgs.openWorkbench;
let pendingProjectRoot = desktopCliArgs.projectRoot;
let cachedDesktopLaunchSettings: DesktopLaunchSettings | null = null;
let pendingWorkbenchCloseAck: PendingWorkbenchCloseAck | null = null;
let electronStartupStage = "electron_process_ready";
let electronStartupSummaryRecorded = false;
let workbenchOpenRequestedAtMs: number | null = null;

type DesktopActionLoopContext = {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
};

type PendingWorkbenchCloseAck = {
  closeId: string;
  desktopSessionId: string;
};

type PublicDeepLinkSource = "open_url" | "second_instance" | "startup";

type PendingPublicDeepLink = {
  rawUrl: string;
  source: PublicDeepLinkSource;
};

const pendingPublicDeepLinks: PendingPublicDeepLink[] = [];
pinSharedDesktopShellUserData(app, { smoke: desktopCliArgs.smoke, env: process.env });
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

function electronStageElapsedMs(startedAtMs: number): number {
  return Math.round(Math.max(0, performance.now() - startedAtMs) * 10) / 10;
}

function electronStartupElapsedMs(): number {
  return electronStageElapsedMs(ELECTRON_PROCESS_STARTED_AT_MS);
}

function electronStartupFields(
  fields: Record<string, string | number | boolean> = {}
): Record<string, string | number | boolean> {
  return {
    startupTraceId: ELECTRON_STARTUP_TRACE_ID,
    processElapsedMs: electronStartupElapsedMs(),
    ...fields
  };
}

function markWorkbenchOpenRequested(): number {
  workbenchOpenRequestedAtMs = performance.now();
  return workbenchOpenRequestedAtMs;
}

async function recordElectronStartupSummaryOnce(
  bootstrap: LauncherBootstrapResult | null,
  fields: Record<string, string | number | boolean>
): Promise<void> {
  if (electronStartupSummaryRecorded || bootstrap === null) {
    return;
  }
  electronStartupSummaryRecorded = true;
  await recordElectronSupervisorEvent(bootstrap, {
    eventCode: "electron.startup.summary",
    message: "Electron startup reached a terminal state.",
    fields: electronStartupFields(fields)
  });
}

function createWindowProvider(paths: DesktopPaths, bootstrap: LauncherBootstrapResult | null): ElectronWindowProvider {
  const desktopEnv = desktopEnvironment();
  conversationNotificationService = null;
  return new ElectronWindowProvider(
    paths,
    resolveLauncherWindowUrl(desktopEnv),
    resolveWorkbenchUrl(desktopEnv, bootstrap?.workbenchUrl),
    {
      createLauncherWindow,
      createWorkbenchWindow,
      listLauncherWindows: (launcherOrigin) =>
        BrowserWindow.getAllWindows().filter((window) => {
          try {
            return launcherAppOriginFor(window.webContents.getURL()) === launcherOrigin;
          } catch {
            return false;
          }
        }),
      listWorkbenchWindows: (workbenchOrigin) =>
        BrowserWindow.getAllWindows().filter((window) => {
          try {
            return new URL(window.webContents.getURL()).origin === workbenchOrigin;
          } catch {
            return false;
          }
        }),
      reportState: (state) => reportManagedWindowState(paths, bootstrap, state),
      shouldInterceptLauncherClose: () => !shutdownApproved,
      shouldInterceptWorkbenchClose: () => !shutdownApproved,
      onWorkbenchCloseRequest: () =>
        requestTransactionalWorkbenchClose(paths, bootstrap).catch((error: unknown) =>
          handleTransactionalWorkbenchCloseFailure(paths, bootstrap, error)
        ),
      onWorkbenchClosed: () =>
        acknowledgeTransactionalWorkbenchClose(paths, bootstrap).catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        }),
      onWorkbenchFocusAttentionClear: () => {
        conversationNotificationService?.clearAttention();
      },
      onOsSessionEnd: (event, role) => {
        const recovery = desktopLifecycleCoordinator.recordSessionEnd();
        void recordElectronSupervisorEvent(bootstrap, {
          eventCode: "electron.lifecycle.os_session_end",
          message: "Electron received a Windows session-end lifecycle signal.",
          fields: {
            event,
            role,
            closeReason: recovery.closeReason,
            recoveryReason: recovery.recoveryReason
          }
        });
      }
    }
  );
}

function createConversationBadgeIcon(count: number) {
  const safeCount = Math.max(1, Math.min(9, Math.round(count)));
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="15" fill="#1f2937"/>
    <text x="16" y="21" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif" font-size="18" font-weight="700" fill="#ffffff">${safeCount}</text>
  </svg>`;
  return nativeImage.createFromDataURL(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`);
}

function toRuntimeSceneFieldValue(value: unknown): string | number | boolean {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (value === null || value === undefined) {
    return "";
  }
  return String(value);
}

function normalizeRuntimeSceneFields(fields: Record<string, unknown>): Record<string, string | number | boolean> {
  return Object.fromEntries(
    Object.entries(fields).map(([key, value]) => [key, toRuntimeSceneFieldValue(value)])
  );
}

function failedConversationNotificationResult(
  payload: DesktopConversationCompletionNotification | null | undefined
): DesktopConversationNotificationResult {
  return {
    schemaVersion: 1,
    status: "failed",
    notificationKey: String(payload?.notificationKey || ""),
    unreadCount: 0,
    focused: false
  };
}

function resolveConversationNotificationService(): ConversationNotificationService | null {
  if (conversationNotificationService !== null) {
    return conversationNotificationService;
  }
  if (windowProvider === null) {
    return null;
  }
  conversationNotificationService = createConversationNotificationService({
    windowProvider,
    notificationSupported: () => Notification.isSupported(),
    createNotification: ({ title, body, onClick }) => {
      const notification = new Notification({ title, body, silent: false });
      notification.on("click", onClick);
      return notification;
    },
    createBadgeIcon: createConversationBadgeIcon,
    notificationOpenedChannel: IPC_CHANNELS.conversationNotificationOpened,
    recordEvent: async (event) => {
      await recordElectronSupervisorEvent(launcherBootstrap, {
        ...event,
        fields: normalizeRuntimeSceneFields(event.fields)
      });
    }
  });
  return conversationNotificationService;
}

async function bootstrapLauncherIfEnabled(paths: DesktopPaths): Promise<LauncherBootstrapResult | null> {
  const desktopEnv = desktopEnvironment();
  if (desktopEnv.VIBELUTION_ELECTRON_START_LAUNCHER === "0") {
    return null;
  }
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    console.warn("Launcher Service bootstrap skipped: no VIBELUTION_PYTHON_PATH, PYTHON, or workspace .venv interpreter.");
    return null;
  }
  electronStartupStage = "control_plane_attach";
  const stageStartedAtMs = performance.now();
  const result = await bootstrapPythonLauncherService({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    operatorConfigPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim()
  });
  const event = {
    eventCode: "electron.startup.control_plane_attached",
    message: "Electron attached to the Launcher control plane.",
    fields: electronStartupFields({
      stage: "control_plane_attach",
      stageDurationMs: electronStageElapsedMs(stageStartedAtMs),
      mode: result.mode,
      launcherBackendPid: result.launcherBackendPid
    })
  };
  return completeBootstrapWithoutWaitingForTelemetry(
    result,
    () => recordElectronSupervisorEvent(result, event)
  );
}

function startDesktopActionLoop(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  provider: ElectronWindowProvider
): void {
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
        waitMs: DESKTOP_ACTION_WAIT_MS,
        operations: {
          openOrFocusWorkbench: (payload) => openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, payload),
          focusWorkbench: () => provider.focusWorkbench(),
          closeWorkbench: (payload) => requestTransactionalWorkbenchClose(paths, bootstrap, payload),
          openOrFocusInstanceWorkbench: (payload) => openIsolatedInstanceWorkbench(provider, payload),
          closeInstanceWorkbench: (payload) =>
            provider.closeInstanceWorkbench(String(payload.instanceId || "").trim())
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
      if (isRecoverableDesktopControlError(error)) {
        await recoverDesktopControlContext(paths, bootstrap, provider, "desktop_action");
      } else {
        console.warn(error instanceof Error ? error.message : String(error));
      }
    } finally {
      desktopActionPollRunning = false;
    }
  };

  void pollOnce();
  desktopActionTimer = setInterval(() => void pollOnce(), DESKTOP_ACTION_POLL_MS);
}

async function openIsolatedInstanceWorkbench(
  provider: ElectronWindowProvider,
  payload: Record<string, unknown> = {}
): Promise<ManagedWindowState> {
  const instanceId = typeof payload.instanceId === "string" ? payload.instanceId.trim() : "";
  const workbenchUrl = typeof payload.workbenchUrl === "string" ? payload.workbenchUrl.trim() : "";
  const windowTitle = typeof payload.windowTitle === "string" ? payload.windowTitle.trim() : "";
  if (!instanceId || !workbenchUrl) {
    throw new Error("instance workbench requires instanceId and workbenchUrl");
  }
  return provider.openOrFocusInstanceWorkbench({
    instanceId,
    url: workbenchUrl,
    title: windowTitle
  });
}

async function openWorkbenchAtCurrentLauncherUrl(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider,
  payload: Record<string, unknown> = {}
): Promise<ManagedWindowState> {
  let workbenchUrl = "";
  const previousWorkbenchUrl = currentWorkbenchUrl;
  electronStartupStage = "workbench_navigation";
  const stageStartedAtMs = markWorkbenchOpenRequested();
  try {
    // A desktop action belongs to the already registered Electron session. Running
    // bootstrap again here can rotate the local control token that this session
    // uses to acknowledge actions, report window state, and close atomically.
    const payloadUrl = typeof payload.workbenchUrl === "string" ? payload.workbenchUrl.trim() : "";
    workbenchUrl = resolveWorkbenchUrl(desktopEnvironment(), payloadUrl || bootstrap.workbenchUrl);
    currentWorkbenchUrl = workbenchUrl;
    const state = await provider.openOrFocusWorkbench(workbenchUrl);
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench.navigation.ready",
      message: "Electron loaded the current Workbench URL before acknowledging the open action.",
      fields: {
        workspaceRoot: paths.workspaceRoot,
        workbenchOrigin: safeOrigin(workbenchUrl),
        windowId: state.windowId,
        rendererProcessId: state.rendererProcessId,
        ...electronStartupFields({
          stage: "workbench_navigation",
          stageDurationMs: electronStageElapsedMs(stageStartedAtMs)
        })
      }
    });
    return state;
  } catch (error: unknown) {
    if (currentWorkbenchUrl === workbenchUrl) {
      currentWorkbenchUrl = previousWorkbenchUrl;
    }
    const detail = error instanceof Error ? error.message : String(error);
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench.navigation.failed",
      message: "Electron could not load the current Workbench URL; the desktop action remains retryable.",
      fields: {
        workspaceRoot: paths.workspaceRoot,
        workbenchOrigin: safeOrigin(workbenchUrl),
        error: detail.slice(0, 300),
        ...electronStartupFields({
          stage: "workbench_navigation",
          stageDurationMs: electronStageElapsedMs(stageStartedAtMs)
        })
      }
    });
    throw error;
  }
}

async function reportManagedWindowState(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  state: ManagedWindowState
): Promise<void> {
  try {
    await persistManagedWindowState(paths, bootstrap, state);
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

async function persistManagedWindowState(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  state: ManagedWindowState
): Promise<void> {
  if (bootstrap === null || !desktopSessionMutations.accepts("window")) {
    return;
  }
  await desktopSessionMutations.enqueue("window", async () => {
    const context = await resolveDesktopActionLoopContext(bootstrap);
    if (!desktopSessionRegistered) {
      electronStartupStage = "desktop_session_registration";
      const stageStartedAtMs = performance.now();
      const registration = inProcessDesktopSessionStore.register({
        desktopSessionId: context.desktopSessionId,
        capabilities: desktopSessionCapabilities(bootstrap)
      });
      desktopSessionRevision = registration.revision;
      desktopSessionRegistered = true;
      void registerDesktopSession({
        ...context,
        workspaceRoot: paths.workspaceRoot,
        capabilities: desktopSessionCapabilities(bootstrap)
      }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
      startDesktopSessionHeartbeatIfNeeded(paths, bootstrap);
      const registrationEvent = {
        eventCode: "electron.startup.desktop_session_registered",
        message: "Electron registered its in-process desktop session.",
        fields: electronStartupFields({
          stage: "desktop_session_registration",
          stageDurationMs: electronStageElapsedMs(stageStartedAtMs),
          desktopSessionId: context.desktopSessionId
        })
      };
      scheduleTelemetryWithoutWaiting(() => recordElectronSupervisorEvent(bootstrap, registrationEvent));
    }
    const result = inProcessDesktopSessionStore.reportWindow({
      desktopSessionId: context.desktopSessionId,
      role: state.role,
      revision: desktopSessionRevision,
      state
    });
    desktopSessionRevision = result.revision;
    void reportDesktopWindowState({
      ...context,
      role: state.role,
      revision: desktopSessionRevision,
      state
    }).catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
    if (state.role === "workbench" && state.open && !electronStartupSummaryRecorded) {
      electronStartupStage = "workbench_window_ready";
      const stageStartedAtMs = workbenchOpenRequestedAtMs ?? ELECTRON_PROCESS_STARTED_AT_MS;
      const readyEvent = {
        eventCode: "electron.startup.workbench_window_ready",
        message: "Electron reported the Workbench window ready.",
        fields: electronStartupFields({
          stage: "workbench_window_ready",
          stageDurationMs: electronStageElapsedMs(stageStartedAtMs),
          desktopSessionId: context.desktopSessionId,
          windowId: state.windowId,
          rendererProcessId: state.rendererProcessId
        })
      };
      scheduleTelemetryWithoutWaiting(async () => {
        await recordElectronSupervisorEvent(bootstrap, readyEvent);
        await recordElectronStartupSummaryOnce(bootstrap, {
          outcome: "succeeded",
          failureStage: "",
          desktopSessionRegistered: true,
          workbenchOpen: true
        });
      });
    }
  });
}

function desktopSessionHeartbeatSupported(
  bootstrap: LauncherBootstrapResult | null
): bootstrap is LauncherBootstrapResult {
  return bootstrap !== null && bootstrap.capabilities.includes(DESKTOP_SESSIONS_HEARTBEAT_CAPABILITY);
}

function startDesktopSessionHeartbeatIfNeeded(paths: DesktopPaths, bootstrap: LauncherBootstrapResult | null): void {
  if (bootstrap === null || desktopSessionHeartbeatTimer !== null || !desktopSessionRegistered) {
    return;
  }
  if (!desktopSessionHeartbeatSupported(bootstrap)) {
    return;
  }
  const heartbeatOnce = async () => {
    if (desktopSessionHeartbeatRunning) {
      return;
    }
    const currentBootstrap = launcherBootstrap;
    if (!desktopSessionRegistered || !desktopSessionHeartbeatSupported(currentBootstrap)) {
      stopDesktopSessionHeartbeat();
      return;
    }
    if (!desktopSessionMutations.accepts("heartbeat")) {
      stopDesktopSessionHeartbeat();
      return;
    }
    desktopSessionHeartbeatRunning = true;
    try {
      await desktopSessionMutations.enqueue("heartbeat", async () => {
        const context = await resolveDesktopActionLoopContext(currentBootstrap);
        const result = inProcessDesktopSessionStore.heartbeat({
          desktopSessionId: context.desktopSessionId,
          revision: desktopSessionRevision
        });
        desktopSessionRevision = result.revision;
        void heartbeatDesktopSession({
          ...context,
          revision: desktopSessionRevision
        }).catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      });
    } catch (error: unknown) {
      if (isRecoverableDesktopControlError(error) && windowProvider !== null) {
        await recoverDesktopControlContext(paths, currentBootstrap, windowProvider, "desktop_session_heartbeat");
      } else {
        console.warn(error instanceof Error ? error.message : String(error));
      }
    } finally {
      desktopSessionHeartbeatRunning = false;
    }
  };
  desktopSessionHeartbeatTimer = setInterval(() => void heartbeatOnce(), DESKTOP_SESSION_HEARTBEAT_MS);
}

function stopDesktopSessionHeartbeat(): void {
  if (desktopSessionHeartbeatTimer !== null) {
    clearInterval(desktopSessionHeartbeatTimer);
    desktopSessionHeartbeatTimer = null;
  }
  desktopSessionHeartbeatRunning = false;
}

async function resolveDesktopActionLoopContext(
  bootstrap: LauncherBootstrapResult,
  options: { forceControlTokenRefresh?: boolean } = {}
): Promise<DesktopActionLoopContext> {
  if (!options.forceControlTokenRefresh && desktopActionContext !== null) {
    return desktopActionContext;
  }
  const desktopEnv = desktopEnvironment();
  const launcherOrigin = resolveLauncherControlPlaneUrl(desktopEnv, bootstrap.launcherUrl);
  const envToken = String(desktopEnv.VIBELUTION_WEB_CONTROL_TOKEN || "").trim();
  const controlToken = options.forceControlTokenRefresh
    ? await fetchLauncherControlToken({ launcherOrigin })
    : envToken || (await fetchLauncherControlToken({ launcherOrigin }));
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

function focusExistingDesktopShell(): void {
  void windowProvider?.openLauncher().catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
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
  return `electron-${bootstrapId}-${DESKTOP_SESSION_GENERATION}`;
}

function desktopSessionCapabilities(bootstrap: LauncherBootstrapResult): string[] {
  return Array.from(new Set([...bootstrap.capabilities, WORKBENCH_CLOSE_TRANSACTION_CAPABILITY])).sort();
}

async function requestTransactionalWorkbenchClose(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  _desktopActionPayload: Record<string, unknown> = {}
): Promise<void> {
  const provider = windowProvider;
  if (provider === null || bootstrap === null) {
    throw new Error("Electron Workbench close transaction requires an active Launcher bootstrap.");
  }
  await desktopLifecycleCoordinator.request("workbench_window_close", async () => {
    const context = await resolveDesktopActionLoopContext(bootstrap);
    let activeWork = false;
    try {
      const status = await withDesktopShellExitTimeout(
        fetchLauncherActiveWorkStatus(context),
        ACTIVE_WORK_STATUS_TIMEOUT_MS,
        "resolve launcher active work status for workbench close"
      );
      activeWork = status.active;
    } catch {
      activeWork = false;
    }
    let transaction = mainWorkbenchCloseStore.submit({
      mode: "normal",
      reason: "workbench_window_close",
      activeWork
    });
    if (transaction.phase === "confirmation_required") {
      const confirmed = await confirmWorkbenchForceClose(provider);
      if (!confirmed) {
        await recordElectronSupervisorEvent(bootstrap, {
          eventCode: "electron.workbench_close.cancelled_active_work",
          message: "Workbench close was cancelled while active work was present.",
          fields: { closeId: transaction.closeId, desktopSessionId: context.desktopSessionId }
        });
        return;
      }
      transaction = mainWorkbenchCloseStore.confirm(transaction.closeId);
    }
    pendingWorkbenchCloseAck = {
      closeId: transaction.closeId,
      desktopSessionId: context.desktopSessionId
    };
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.backend_stopping",
      message: "Electron is stopping the workbench backend through the Python lifecycle bridge.",
      fields: { closeId: transaction.closeId, desktopSessionId: context.desktopSessionId }
    });
    await stopWorkbenchBackend(paths, bootstrap);
    const backendStopped = await waitForWorkbenchBackendClosed(context, WORKBENCH_CLOSE_BACKEND_WAIT_MS);
    if (!backendStopped) {
      mainWorkbenchCloseStore.fail(
        transaction.closeId,
        "backend_stop_timeout",
        "Workbench backend did not settle closed before window authorization."
      );
      throw new Error("Workbench backend did not settle closed before window authorization.");
    }
    transaction = mainWorkbenchCloseStore.backendStopped(transaction.closeId);
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.window_authorized",
      message: "Workbench backend closed; Electron is requesting the final window close.",
      fields: {
        closeId: transaction.closeId,
        desktopSessionId: context.desktopSessionId,
        phase: transaction.phase
      }
    });
    await provider.approveWorkbenchCloseOnce();
  });
}

async function stopWorkbenchBackend(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult
): Promise<void> {
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to stop the workbench backend");
  }
  await runWorkbenchLifecycle({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    operatorConfigPath:
      bootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    operation: "stop"
  });
}

async function waitForWorkbenchBackendClosed(
  context: DesktopActionLoopContext,
  timeoutMs: number
): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const summary = await fetchLauncherStatusSummary(context);
      if (String(summary.observedState || "").trim().toLowerCase() === "closed") {
        return true;
      }
    } catch {
      // Treat control-plane read failures as not-yet-closed; the next poll retries.
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return false;
}

function isRecoverableDesktopControlError(error: unknown): boolean {
  const detail = (error instanceof Error ? error.message : String(error)).toLowerCase();
  return (
    /(?:^|\D)(?:401|403)(?:\D|$)/.test(detail) ||
    detail.includes("unauthorized") ||
    detail.includes("forbidden") ||
    detail.includes("control context")
  );
}

async function recoverDesktopControlContext(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider,
  reason: string
): Promise<void> {
  if (desktopControlRecoveryPromise !== null) {
    return await desktopControlRecoveryPromise;
  }
  desktopControlRecoveryPromise = (async () => {
    const previousContext = desktopActionContext;
    stopDesktopSessionHeartbeat();
    desktopActionContext = null;
    runtimeSceneBridge = null;
    desktopSessionRegistered = false;
    const refreshedContext = await resolveDesktopActionLoopContext(bootstrap, { forceControlTokenRefresh: true });
    if (previousContext !== null && refreshedContext.desktopSessionId !== previousContext.desktopSessionId) {
      throw new Error("Electron control recovery changed the desktop session identity.");
    }
    await persistManagedWindowState(paths, bootstrap, provider.snapshot().workbench);
    if (!desktopSessionRegistered) {
      throw new Error("Electron control recovery could not re-register the active desktop session.");
    }
    scheduleTelemetryWithoutWaiting(() => recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.desktop_control.recovered",
      message: "Electron refreshed its Launcher control context and resumed the existing desktop session.",
      fields: {
        desktopSessionId: refreshedContext.desktopSessionId,
        workspaceRoot: paths.workspaceRoot,
        reason: reason.slice(0, 80)
      }
    }));
  })();
  try {
    await desktopControlRecoveryPromise;
  } finally {
    desktopControlRecoveryPromise = null;
  }
}

async function recoverWorkbenchCloseControlContext(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider
): Promise<void> {
  await recoverDesktopControlContext(paths, bootstrap, provider, "workbench_close");
}

async function acknowledgeTransactionalWorkbenchClose(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null
): Promise<void> {
  const pending = pendingWorkbenchCloseAck;
  if (pending === null || bootstrap === null) {
    return;
  }
  const transaction = mainWorkbenchCloseStore.get(pending.closeId);
  pendingWorkbenchCloseAck = null;
  if (transaction === null) {
    return;
  }
  mainWorkbenchCloseStore.windowClosed(transaction.closeId);
  const context = await resolveDesktopActionLoopContext(bootstrap);
  writeWorkbenchCloseCanarySummary(paths, {
    closeId: transaction.closeId,
    desktopSessionId: context.desktopSessionId,
    desktopSessionRevision,
    controlToken: context.controlToken
  });
  await recordElectronSupervisorEvent(bootstrap, {
    eventCode: "electron.workbench_close.completed",
    message: "Electron confirmed the Workbench closed after the backend stopped.",
    fields: {
      closeId: transaction.closeId,
      desktopSessionId: context.desktopSessionId,
      desktopSessionRevision,
      workspaceRoot: paths.workspaceRoot
    }
  });
}

function writeWorkbenchCloseCanarySummary(
  paths: DesktopPaths,
  input: {
    closeId: string;
    desktopSessionId: string;
    desktopSessionRevision: number;
    controlToken: string;
  }
): void {
  if (!desktopCliArgs.workbenchCloseCanary) {
    return;
  }
  const summaryPath = desktopWorkbenchCloseCanarySummaryPath(paths.workspaceRoot);
  mkdirSync(dirname(summaryPath), { recursive: true });
  writeFileSync(
    summaryPath,
    JSON.stringify(
      desktopWorkbenchCloseCanarySummary({
        workspaceRoot: paths.workspaceRoot,
        configPath: String(desktopEnvironment().VIBELUTION_CONFIG_PATH || "").trim(),
        ...input
      }),
      null,
      2
    ),
    "utf8"
  );
}

async function handleTransactionalWorkbenchCloseFailure(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult | null,
  error: unknown
): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  await recordElectronSupervisorEvent(bootstrap, {
    eventCode: "electron.workbench_close.failed",
    message: "Workbench close transaction failed before Electron window authorization.",
    fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
  });
  const provider = windowProvider;
  if (provider === null) {
    console.warn(message);
    return;
  }
  if (isWorkbenchCloseControlFetchFailure(error)) {
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.fail_open_destroy",
      message: "Workbench close control fetch failed; Electron is destroying the window.",
      fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
    });
    await provider.approveWorkbenchCloseOnce();
    return;
  }
  const retry = await confirmWorkbenchCloseRetry(provider, message);
  if (!retry) {
    await provider.approveWorkbenchCloseOnce();
    return;
  }
  setTimeout(() => {
    void requestTransactionalWorkbenchClose(paths, bootstrap).catch((retryError: unknown) =>
      handleTransactionalWorkbenchCloseFailure(paths, bootstrap, retryError)
    );
  }, 0);
}

async function confirmWorkbenchForceClose(provider: ElectronWindowProvider): Promise<boolean> {
  const options = {
    type: "warning" as const,
    title: "仍有进行中的任务",
    message: "关闭工作台会中断正在运行的任务。",
    detail: "选择“继续运行”会保留窗口、后端和当前任务。",
    buttons: ["继续运行", "停止任务并关闭"],
    defaultId: 0,
    cancelId: 0,
    noLink: true
  };
  const parent = provider.workbenchDialogParent() as unknown as BrowserWindow | null;
  const response = parent === null ? await dialog.showMessageBox(options) : await dialog.showMessageBox(parent, options);
  return response.response === 1;
}

async function confirmWorkbenchCloseRetry(provider: ElectronWindowProvider, detail: string): Promise<boolean> {
  const options = {
    type: "error" as const,
    title: "工作台未关闭",
    message: "后端关闭未完成。可以选择重试，或直接关闭窗口。",
    detail: detail.slice(0, 500),
    buttons: ["重试", "仍关闭窗口"],
    defaultId: 1,
    cancelId: 1,
    noLink: true
  };
  const parent = provider.workbenchDialogParent() as unknown as BrowserWindow | null;
  const response = parent === null ? await dialog.showMessageBox(options) : await dialog.showMessageBox(parent, options);
  return response.response === 0;
}

function stopDesktopActionLoop(): void {
  if (desktopActionTimer !== null) {
    clearInterval(desktopActionTimer);
    desktopActionTimer = null;
  }
  desktopActionPollRunning = false;
  stopDesktopSessionHeartbeat();
}

async function closeDesktopSessionIfRegistered(): Promise<void> {
  if (!desktopSessionRegistered || launcherBootstrap === null) {
    return;
  }
  const bootstrap = launcherBootstrap;
  stopDesktopSessionHeartbeat();
  try {
    await desktopSessionMutations.enqueue("close", async () => {
      const context = await resolveDesktopActionLoopContext(bootstrap);
      const result = inProcessDesktopSessionStore.close({
        desktopSessionId: context.desktopSessionId,
        revision: desktopSessionRevision
      });
      desktopSessionRevision = result.revision;
      desktopSessionRegistered = false;
      void closeDesktopSession({
        ...context,
        revision: desktopSessionRevision
      }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
    });
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
  const workbenchUrl = currentWorkbenchUrl || resolveWorkbenchUrl(desktopEnv, launcherBootstrap?.workbenchUrl);
  return Array.from(
    new Set([
      launcherAppOriginFor(resolveLauncherWindowUrl(desktopEnv)),
      new URL(workbenchUrl).origin
    ])
  );
}

async function requestDesktopShellExit(
  closeReason: DesktopCloseReason = "desktop_shell_quit"
): Promise<ShutdownDecision> {
  return desktopLifecycleCoordinator.request(closeReason, async () => {
    const ownershipMode = launcherBootstrap?.mode ?? "attached";
    return await executeShutdownAuthorizationBoundary({
      authorize: async () =>
        await decideShutdown({
        ownershipMode,
        activeWorkStatus: async () => {
          if (launcherBootstrap === null) {
            return { active: false, message: "" };
          }
          return await withDesktopShellExitTimeout(
            (async () => {
              const context = await resolveDesktopActionLoopContext(launcherBootstrap);
              return await fetchLauncherActiveWorkStatus(context);
            })(),
            ACTIVE_WORK_STATUS_TIMEOUT_MS,
            "resolve launcher active work status for quit"
          );
        }
      }),
      onDenied: (decision) => {
        notifyDesktopTray("Vibelution", decision.message || "有进行中的任务，暂时无法退出。可先用托盘“停止全部”。", "warning");
      },
      runApproved: async (decision) => {
        pendingWorkbenchCloseAck = null;
        await withDesktopShellExitTimeout(
          executeApprovedDesktopShellShutdown({
            decision,
            closeDesktopSession: closeDesktopSessionIfRegistered,
            recordEvent: async (event) => {
              await recordElectronSupervisorEvent(launcherBootstrap, {
                ...event,
                fields: {
                  closeReason,
                  ownershipMode,
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
            },
            stepTimeoutMs: DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS
          }),
          DESKTOP_SHELL_EXIT_BUDGET_MS,
          "desktop shell exit"
        );
      },
      failOpenAfterApproval: async (_decision, error) => {
        const message = error instanceof Error ? error.message : String(error);
        console.warn(message);
        await recordElectronSupervisorEvent(launcherBootstrap, {
          eventCode: "electron.launcher_service.exited",
          message: "Desktop shell exit budget exceeded; forcing Electron quit.",
          fields: { closeReason, error: message.slice(0, 500), failOpen: true }
        }).catch(() => undefined);
        shutdownApproved = true;
        pendingWorkbenchCloseAck = null;
        // Best-effort stop owned Python before force quit so orphans are less likely.
        try {
          await withDesktopShellExitTimeout(
            stopOwnedPythonLauncherService(),
            Math.min(3_000, DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS),
            "stop python launcher on exit budget fail-open"
          );
        } catch {
          // Fail-open: stop must not block the forced Electron quit.
        }
        stopDesktopActionLoop();
        releaseElectronDesktopShellOwner(createDesktopPathsForApp().workspaceRoot);
        desktopTray?.destroy();
        desktopTray = null;
        app.quit();
      }
    });
  });
}

function notifyDesktopTray(title: string, body: string, type: "info" | "warning" = "info"): void {
  if (Notification.isSupported()) {
    new Notification({ title, body, silent: type === "info" }).show();
    return;
  }
  void dialog
    .showMessageBox({
      type,
      title,
      message: body,
      buttons: ["确定"],
      defaultId: 0,
      noLink: true
    })
    .catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
}

async function resolveTrayLauncherControlContext(): Promise<DesktopActionLoopContext> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  return resolveDesktopActionLoopContext(launcherBootstrap);
}

async function resolveTrayControlContextOrLoopback(): Promise<{
  launcherOrigin: string;
  controlToken: string;
}> {
  try {
    return await resolveTrayLauncherControlContext();
  } catch {
    return {
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: ""
    };
  }
}

async function restartLauncherShell(): Promise<void> {
  notifyDesktopTray("Vibelution", "正在重启 Launcher，以加载最新本地代码…");
  try {
    await stopOwnedPythonLauncherService();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止旧 Launcher 服务失败，仍将重启：${detail.slice(0, 220)}`, "warning");
  }
  app.relaunch();
  shutdownApproved = true;
  app.exit(0);
}

async function runTrayLauncherPost(
  path: LauncherControlPostPath,
  label: string,
  trigger?: string,
  body?: Record<string, unknown>
): Promise<void> {
  try {
    const context = await resolveTrayLauncherControlContext();
    await postLauncherControl({
      launcherOrigin: context.launcherOrigin,
      controlToken: context.controlToken,
      path,
      trigger,
      body
    });
    notifyDesktopTray("Vibelution", `${label}请求已发送。`);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `${label}失败：${detail.slice(0, 300)}`, "warning");
  }
}

async function runTrayLifecycle(operation: WorkbenchLifecycleOperation, label: string): Promise<void> {
  try {
    await orchestrateLauncherLifecycle(operation, { schemaVersion: 1, path: operation });
    notifyDesktopTray("Vibelution", `${label}请求已发送。`);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `${label}失败：${detail.slice(0, 300)}`, "warning");
  }
}

async function runTrayLauncherStatus(): Promise<void> {
  try {
    const context = await resolveTrayLauncherControlContext();
    const summary = await fetchLauncherStatusSummary(context);
    notifyDesktopTray("Vibelution", formatLauncherStatusSummary(summary));
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `获取状态失败：${detail.slice(0, 300)}`, "warning");
  }
}

async function runTrayStopAll(): Promise<void> {
  try {
    await orchestrateLauncherLifecycle("force-stop", { schemaVersion: 1, path: "force-stop" });
    await new Promise((resolve) => setTimeout(resolve, 1500));
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止全部失败：${detail.slice(0, 300)}`, "warning");
    return;
  }
  try {
    await requestDesktopShellExit();
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
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

ipcMain.handle(IPC_CHANNELS.notifyConversationCompleted, async (event, payload: DesktopConversationCompletionNotification) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  const service = resolveConversationNotificationService();
  if (service === null) {
    return failedConversationNotificationResult(payload);
  }
  return await service.notify(payload);
});

function launcherIpcTrustedOrigins(): string[] {
  const desktopEnv = desktopEnvironment();
  return [launcherAppOriginFor(resolveLauncherWindowUrl(desktopEnv))];
}

async function orchestrateLauncherLifecycle(
  operation: string,
  _payload: LauncherIpcInvokePayload
): Promise<OrchestratedLifecycleResult> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to orchestrate the workbench lifecycle");
  }
  const paths = createDesktopPathsForApp();
  const result = await runWorkbenchLifecycle({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    operatorConfigPath:
      launcherBootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    operation: operation as WorkbenchLifecycleOperation
  });
  if (result.accepted && (operation === "start" || operation === "rebuild-and-start")) {
    const provider = windowProvider;
    if (provider !== null) {
      void provider
        .openOrFocusWorkbench(resolveWorkbenchUrl(desktopEnv, launcherBootstrap.workbenchUrl))
        .catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
    }
  }
  return result;
}

async function orchestrateBranchInstanceLifecycle(
  operation: string,
  payload: LauncherIpcInvokePayload
): Promise<OrchestratedBranchInstanceResult> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to orchestrate branch instances");
  }
  const body = payload.init?.body;
  const instanceId =
    typeof body === "object" && body !== null
      ? String((body as Record<string, unknown>).instanceId ?? "").trim()
      : "";
  if (!instanceId) {
    throw new Error("branch instance id is required");
  }
  const paths = createDesktopPathsForApp();
  const result = await runBranchInstanceBridge({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    operatorConfigPath:
      launcherBootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    operation: operation as BranchInstanceOperation,
    instanceId
  });
  if (
    result.accepted
    && (operation === "start" || operation === "restart")
    && result.port
    && result.port > 0
  ) {
    const provider = windowProvider;
    if (provider !== null) {
      void provider
        .openOrFocusInstanceWorkbench({
          instanceId,
          url: `http://127.0.0.1:${result.port}/`
        })
        .catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
    }
  }
  return result;
}

async function orchestrateLauncherApi(
  path: string,
  payload: LauncherIpcInvokePayload
): Promise<unknown> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required for the launcher API bridge");
  }
  const paths = createDesktopPathsForApp();
  const method = String(payload.init?.method ?? "GET").toUpperCase();
  const body = payload.init?.body;
  const args = [
    resolve(paths.workspaceRoot, "scripts", "vibelution_desktop_entry.py"),
    "--action",
    "launcher-api",
    "--launcher-api-path",
    path,
    "--launcher-api-method",
    method,
    ...(body !== undefined ? ["--launcher-api-body", JSON.stringify(body)] : []),
    "--output",
    "json",
    "--workspace",
    paths.workspaceRoot,
    "--config",
    launcherBootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    "--no-browser"
  ];
  const raw = await runPythonJsonBridge({
    pythonPath,
    args,
    cwd: paths.workspaceRoot,
    failureLabel: "launcher api bridge"
  });
  const parsed = JSON.parse(raw) as { ok?: boolean; payload?: unknown; message?: string };
  if (parsed.ok !== true) {
    throw new Error(parsed.message || "launcher api bridge failed");
  }
  return parsed.payload;
}

function resolveLauncherIpcHost() {
  if (launcherIpcHost !== null) {
    return launcherIpcHost;
  }
  launcherIpcHost = createLauncherIpcHost({
    resolveContext: async () => {
      if (launcherBootstrap === null) {
        return null;
      }
      const context = await resolveDesktopActionLoopContext(launcherBootstrap);
      return {
        launcherOrigin: context.launcherOrigin,
        controlToken: context.controlToken
      };
    },
    resolveWindowTruth: () => {
      const provider = windowProvider;
      const snapshot = provider?.snapshot();
      return {
        workbench: snapshot?.workbench.open
          ? { open: true, rendererProcessId: snapshot.workbench.rendererProcessId }
          : null,
        instances: provider ? provider.instanceWindowStates() : []
      };
    },
    orchestrateLifecycle: orchestrateLauncherLifecycle,
    orchestrateBranchInstance: orchestrateBranchInstanceLifecycle,
    orchestrateLauncherApi
  });
  return launcherIpcHost;
}

ipcMain.handle(IPC_CHANNELS.launcherInvoke, async (event, payload: LauncherIpcInvokePayload) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return await resolveLauncherIpcHost().invoke(payload);
});

function requestOpenWorkbench(): void {
  const provider = windowProvider;
  if (provider === null) {
    pendingOpenWorkbenchRequest = true;
    return;
  }
  pendingOpenWorkbenchRequest = false;
  markWorkbenchOpenRequested();
  void provider.openOrFocusWorkbench().catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
}

async function requestOpenWorkbenchFromSecondInstance(): Promise<void> {
  const provider = windowProvider;
  if (provider === null) {
    pendingOpenWorkbenchRequest = true;
    return;
  }
  const bootstrap = launcherBootstrap;
  if (bootstrap !== null) {
    const paths = createDesktopPathsForApp();
    await recoverDesktopControlContext(paths, bootstrap, provider, "second_instance_open_workbench");
  }
  pendingOpenWorkbenchRequest = false;
  markWorkbenchOpenRequested();
  await provider.openOrFocusWorkbench();
}

async function applyPendingProjectSlot(projectRoot: string): Promise<void> {
  const wanted = projectRoot.trim();
  if (!wanted) {
    return;
  }
  const provider = windowProvider;
  if (provider === null || launcherBootstrap === null) {
    pendingProjectRoot = wanted;
    return;
  }
  pendingProjectRoot = "";
  try {
    const context = await resolveTrayLauncherControlContext();
    const result = await applyProjectSlot({
      projectRoot: wanted,
      launcherOrigin: context.launcherOrigin,
      controlToken: context.controlToken
    });
    currentWorkbenchUrl = result.url;
    markWorkbenchOpenRequested();
    await provider.openOrFocusWorkbench(result.url);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `应用工作区失败：${detail.slice(0, 300)}`, "warning");
  }
}

app.whenReady()
  .then(async () => {
    const paths = createDesktopPathsForApp();
    registerLauncherAppProtocolHandle({
      distRoot: resolveLauncherDistRoot({
        resourcesRoot: paths.resourcesRoot,
        workspaceRoot: paths.workspaceRoot,
        packaged: app.isPackaged,
        env: desktopEnvironment()
      })
    });
    if (desktopCliArgs.smoke) {
      await runSmokeAndQuit(paths);
      return;
    }
    const deepLinkRegistration = registerPackagedDeepLinks(paths);
    launcherBootstrap = await bootstrapLauncherIfEnabled(paths);
    electronStartupStage = "tray_ready";
    const trayStartedAtMs = performance.now();
    windowProvider = createWindowProvider(paths, launcherBootstrap);
    desktopTray = createDesktopTray(paths, {
      openLauncher: () => {
        void windowProvider?.openLauncher().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      },
      listInstances: async () => {
        return fetchLauncherBranchInstances({
          ...(await resolveTrayControlContextOrLoopback()),
          requestTimeoutMs: 20_000
        });
      },
      getFreshness: async () => {
        return fetchLauncherFreshness({
          ...(await resolveTrayControlContextOrLoopback()),
          requestTimeoutMs: 20_000
        });
      },
      restartLauncher: () => {
        void restartLauncherShell();
      },
      startInstance: (instanceId, label) => {
        void runTrayLauncherPost(
          "/api/launcher/branch-instances/start",
          `启动 ${label}`,
          "electron_tray_start_instance",
          { instanceId }
        );
      },
      stopInstance: (instanceId, label) => {
        void runTrayLauncherPost(
          "/api/launcher/branch-instances/stop",
          `停止 ${label}`,
          "electron_tray_stop_instance",
          { instanceId }
        );
      },
      restartProject: () => {
        void runTrayLifecycle("restart", DESKTOP_TRAY_MENU_LABELS.restartProject);
      },
      rebuildAndStart: () => {
        void runTrayLifecycle("rebuild-and-start", DESKTOP_TRAY_MENU_LABELS.rebuildAndStart);
      },
      showStatus: () => {
        void runTrayLauncherStatus();
      },
      quit: () => {
        void requestDesktopShellExit().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      },
      stopAll: () => {
        void runTrayStopAll();
      }
    });
    claimElectronDesktopShellOwner(paths.workspaceRoot);
    await recordElectronSupervisorEvent(launcherBootstrap, {
      eventCode: "electron.tray.created",
      message: "Electron system tray created.",
      fields: { provider: "electron" }
    });
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
      eventCode: "electron.tray.ready",
      message: "Lightweight tray started.",
      fields: electronStartupFields({
        provider: "electron",
        stage: "tray_ready",
        stageDurationMs: electronStageElapsedMs(trayStartedAtMs)
      })
    });
    const rawUrl = findVibelutionDeepLinkArg(process.argv.slice(1));
    if (rawUrl) {
      await handlePublicDeepLinkUrl(rawUrl, "startup");
    }
    await flushPendingPublicDeepLinks();
    if (pendingProjectRoot) {
      await applyPendingProjectSlot(pendingProjectRoot);
    }
    if (pendingOpenWorkbenchRequest && !desktopCliArgs.workbenchCloseCanary) {
      pendingOpenWorkbenchRequest = false;
      electronStartupStage = "workbench_window_ready";
      markWorkbenchOpenRequested();
      await windowProvider.openOrFocusWorkbench();
    } else if (!desktopCliArgs.workbenchCloseCanary && !desktopCliArgs.projectRoot) {
      await windowProvider.openLauncher();
    }
    if (desktopCliArgs.workbenchCloseCanary) {
      await windowProvider.openOrFocusWorkbench();
      return;
    }
    // T6: window actions are orchestrated by Electron main; the Python desktop
    // action claim loop is no longer polled. startDesktopActionLoop stays
    // available for shutdown bookkeeping but is not started here.
    if (!desktopCliArgs.openWorkbench && !desktopCliArgs.projectRoot) {
      scheduleTelemetryWithoutWaiting(() =>
        recordElectronStartupSummaryOnce(launcherBootstrap, {
          outcome: "succeeded",
          failureStage: "",
          desktopSessionRegistered,
          workbenchOpen: false
        })
      );
    }
  })
  .catch(async (error: unknown) => {
    await drainTelemetryWithDeadline(() =>
      recordElectronStartupSummaryOnce(launcherBootstrap, {
        outcome: "failed",
        failureStage: electronStartupStage,
        errorType: error instanceof Error ? error.name : "Error",
        desktopSessionRegistered,
        workbenchOpen: false
      })
    );
    console.error(error instanceof Error ? error.message : String(error));
    app.quit();
  });

app.on("second-instance", (_event, argv) => {
  const secondCli = parseDesktopCliArgs(argv);
  const intent = resolveSecondInstanceIntent({
    deepLinkUrl: findVibelutionDeepLinkArg(argv) ?? "",
    projectRoot: secondCli.projectRoot,
    openWorkbench: secondCli.openWorkbench
  });
  if (secondCli.lifecycleCommand === "open") {
    void requestOpenWorkbenchFromSecondInstance().catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
    return;
  }
  if (secondCli.lifecycleCommand && secondCli.lifecycleCommand !== "open") {
    void handleSecondInstanceLifecycleCommand(secondCli.lifecycleCommand).catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
    return;
  }
  if (intent.action === "handle_deep_link") {
    void handlePublicDeepLinkUrl(intent.rawUrl, "second_instance");
    return;
  }
  if (intent.action === "apply_project") {
    void applyPendingProjectSlot(intent.projectRoot);
    return;
  }
  if (intent.action === "open_workbench") {
    void requestOpenWorkbenchFromSecondInstance().catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
    return;
  }
  if (intent.action === "focus_existing_shell") {
    focusExistingDesktopShell();
  }
});

async function handleSecondInstanceLifecycleCommand(command: string): Promise<void> {
  if (command === "status") {
    focusExistingDesktopShell();
    return;
  }
  if (command === "toggle") {
    if (launcherBootstrap === null) {
      return;
    }
    try {
      const context = await resolveDesktopActionLoopContext(launcherBootstrap);
      const summary = await fetchLauncherStatusSummary(context);
      const observed = String(summary.observedState || "").trim().toLowerCase();
      await orchestrateLauncherLifecycle(
        observed === "open" || observed === "running" || observed === "starting" ? "stop" : "start",
        { schemaVersion: 1, path: "toggle" }
      );
    } catch (error: unknown) {
      notifyDesktopTray("Vibelution", `切换失败：${error instanceof Error ? error.message.slice(0, 220) : String(error)}`, "warning");
    }
    return;
  }
  const operation = command === "rebuild-and-start" ? "rebuild-and-start" : command;
  try {
    await orchestrateLauncherLifecycle(operation, { schemaVersion: 1, path: command });
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `Launcher 命令失败：${detail.slice(0, 300)}`, "warning");
  }
}

app.on("open-url", (event, rawUrl) => {
  event.preventDefault();
  void handlePublicDeepLinkUrl(rawUrl, "open_url");
});

app.on("before-quit", (event) => {
  if (shutdownApproved) {
    releaseElectronDesktopShellOwner(createDesktopPathsForApp().workspaceRoot);
    desktopTray?.destroy();
    desktopTray = null;
    stopDesktopActionLoop();
    return;
  }
  event.preventDefault();
  void requestDesktopShellExit().catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
});

app.on("window-all-closed", () => {
  // Keep the lightweight tray app running after the Launcher/workbench windows close.
});
