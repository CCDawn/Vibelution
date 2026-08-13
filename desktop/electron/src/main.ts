import { Notification, app, dialog, ipcMain, nativeImage, nativeTheme, type BrowserWindow } from "electron";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";
import { performance } from "node:perf_hooks";
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
  acknowledgeWorkbenchCloseWindowClosed,
  fetchWorkbenchCloseTransaction,
  isRecoverableWorkbenchCloseTransactionControlRejection,
  retryRejectedWorkbenchCloseSubmitOnce,
  submitWorkbenchCloseTransaction,
  type WorkbenchCloseTransaction
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
import { ElectronWindowProvider } from "./windows/electronWindowProvider.js";
import type { ManagedWindowState } from "./windows/windowProviderTypes.js";
import { createLauncherWindow } from "./windows/launcherWindow.js";
import { createWorkbenchWindow } from "./windows/workbenchWindow.js";
import { resolveLauncherUrl, resolveWorkbenchUrl } from "./windows/windowUrlResolver.js";
import { installBrokenPipeGuards } from "./runtime/brokenPipeGuard.js";

installBrokenPipeGuards();

const DESKTOP_ACTION_POLL_MS = 2000;
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
    resolveLauncherUrl(desktopEnv, bootstrap?.launcherUrl),
    resolveWorkbenchUrl(desktopEnv, bootstrap?.workbenchUrl),
    {
      createLauncherWindow,
      createWorkbenchWindow,
      reportState: (state) => reportManagedWindowState(paths, bootstrap, state),
      shouldInterceptLauncherClose: () => !shutdownApproved,
      shouldInterceptWorkbenchClose: () => true,
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
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to bootstrap the Launcher Service");
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
        operations: {
          openOrFocusWorkbench: (payload) => openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, payload),
          focusWorkbench: () => provider.focusWorkbench(),
          closeWorkbench: (payload) => requestTransactionalWorkbenchClose(paths, bootstrap, payload)
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
      const registration = await registerDesktopSession({
        ...context,
        workspaceRoot: paths.workspaceRoot,
        capabilities: desktopSessionCapabilities(bootstrap)
      });
      desktopSessionRevision = registration.revision;
      desktopSessionRegistered = true;
      startDesktopSessionHeartbeatIfNeeded(paths, bootstrap);
      const registrationEvent = {
        eventCode: "electron.startup.desktop_session_registered",
        message: "Electron registered its scoped desktop session.",
        fields: electronStartupFields({
          stage: "desktop_session_registration",
          stageDurationMs: electronStageElapsedMs(stageStartedAtMs),
          desktopSessionId: context.desktopSessionId
        })
      };
      scheduleTelemetryWithoutWaiting(() => recordElectronSupervisorEvent(bootstrap, registrationEvent));
    }
    const result = await reportDesktopWindowState({
      ...context,
      role: state.role,
      revision: desktopSessionRevision,
      state
    });
    desktopSessionRevision = result.revision;
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
        const result = await heartbeatDesktopSession({
          ...(await resolveDesktopActionLoopContext(currentBootstrap)),
          revision: desktopSessionRevision
        });
        desktopSessionRevision = result.revision;
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
  const launcherOrigin = resolveLauncherUrl(desktopEnv, bootstrap.launcherUrl);
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
  desktopActionPayload: Record<string, unknown> = {}
): Promise<void> {
  const provider = windowProvider;
  if (provider === null || bootstrap === null) {
    throw new Error("Electron Workbench close transaction requires an active Launcher bootstrap.");
  }
  await desktopLifecycleCoordinator.request("workbench_window_close", async () => {
    if (!desktopSessionRegistered) {
      await reportManagedWindowState(paths, bootstrap, provider.snapshot().workbench);
    }
    if (!desktopSessionRegistered) {
      throw new Error("Electron Workbench close transaction requires an active desktop session.");
    }
    let context = await resolveDesktopActionLoopContext(bootstrap);
    const existingCloseId = closeTransactionIdFromDesktopAction(desktopActionPayload, context.desktopSessionId);
    let transaction: WorkbenchCloseTransaction;
    if (existingCloseId) {
      transaction = await fetchWorkbenchCloseTransactionWithControlRecovery(paths, bootstrap, provider, {
        ...context,
        closeId: existingCloseId
      });
    } else {
      const normalIdempotencyKey = `electron-workbench-close:${context.desktopSessionId}:${randomUUID()}`;
      transaction = await submitWorkbenchCloseTransactionWithControlRecovery(paths, bootstrap, provider, {
        idempotencyKey: normalIdempotencyKey,
        mode: "normal",
        reason: "workbench_window_close"
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
        transaction = await submitWorkbenchCloseTransactionWithControlRecovery(paths, bootstrap, provider, {
          idempotencyKey: `${normalIdempotencyKey}:force`,
          mode: "force",
          reason: "workbench_window_close",
          confirmationCloseId: transaction.closeId
        });
      }
    }
    // A recovered submit replaces the cached control context. Refresh this
    // local handle before polling and acknowledging the same close transaction.
    context = await resolveDesktopActionLoopContext(bootstrap);
    transaction = await awaitWorkbenchCloseAuthorization(context, transaction);
    if (transaction.phase !== "window_close_authorized") {
      throw new Error(workbenchCloseTransactionFailureMessage(transaction));
    }
    pendingWorkbenchCloseAck = {
      closeId: transaction.closeId,
      desktopSessionId: context.desktopSessionId
    };
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.window_authorized",
      message: "Workbench backend close completed; Electron is requesting the final window close.",
      fields: {
        closeId: transaction.closeId,
        desktopSessionId: context.desktopSessionId,
        phase: transaction.phase
      }
    });
    await provider.approveWorkbenchCloseOnce();
  });
}

function closeTransactionIdFromDesktopAction(
  payload: Record<string, unknown>,
  desktopSessionId: string
): string {
  const targetSessionId = String(payload.desktopSessionId || "").trim();
  const closeId = String(payload.closeId || "").trim();
  if (!closeId || targetSessionId !== desktopSessionId) {
    return "";
  }
  return closeId;
}

async function submitWorkbenchCloseTransactionWithControlRecovery(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider,
  input: {
    idempotencyKey: string;
    mode: "normal" | "force";
    reason: string;
    confirmationCloseId?: string;
  }
): Promise<WorkbenchCloseTransaction> {
  return await retryRejectedWorkbenchCloseSubmitOnce(
    async () =>
      await submitWorkbenchCloseTransaction({
        ...(await resolveDesktopActionLoopContext(bootstrap)),
        ...input
      }),
    async () => await recoverWorkbenchCloseControlContext(paths, bootstrap, provider)
  );
}

async function fetchWorkbenchCloseTransactionWithControlRecovery(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider,
  input: DesktopActionLoopContext & { closeId: string }
): Promise<WorkbenchCloseTransaction> {
  try {
    return await fetchWorkbenchCloseTransaction(input);
  } catch (error: unknown) {
    if (!isRecoverableWorkbenchCloseTransactionControlRejection(error, "fetch")) {
      throw error;
    }
    await recoverWorkbenchCloseControlContext(paths, bootstrap, provider);
    return await fetchWorkbenchCloseTransaction({ ...(await resolveDesktopActionLoopContext(bootstrap)), closeId: input.closeId });
  }
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
  const context = await resolveDesktopActionLoopContext(bootstrap);
  if (context.desktopSessionId !== pending.desktopSessionId) {
    throw new Error("Electron Workbench close acknowledgement desktop session changed before the window closed.");
  }
  const transaction = await acknowledgeWorkbenchCloseWindowClosed({
    ...context,
    closeId: pending.closeId,
    desktopSessionRevision
  });
  if (transaction.phase !== "succeeded") {
    throw new Error(workbenchCloseTransactionFailureMessage(transaction));
  }
  pendingWorkbenchCloseAck = null;
  writeWorkbenchCloseCanarySummary(paths, {
    closeId: transaction.closeId,
    desktopSessionId: context.desktopSessionId,
    desktopSessionRevision,
    controlToken: context.controlToken
  });
  await recordElectronSupervisorEvent(bootstrap, {
    eventCode: "electron.workbench_close.completed",
    message: "Electron confirmed the Workbench closed after the backend close transaction completed.",
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

async function awaitWorkbenchCloseAuthorization(
  context: DesktopActionLoopContext,
  initialTransaction: WorkbenchCloseTransaction
): Promise<WorkbenchCloseTransaction> {
  let transaction = initialTransaction;
  const startedAt = Date.now();
  while (transaction.phase === "backend_closing") {
    if (Date.now() - startedAt >= WORKBENCH_CLOSE_AUTHORIZATION_MAX_WAIT_MS) {
      throw new Error(
        `Workbench backend close authorization timed out after ${WORKBENCH_CLOSE_AUTHORIZATION_MAX_WAIT_MS}ms`
      );
    }
    const deadlineEpochMs = Date.parse(String(transaction.deadlineAt || ""));
    if (Number.isFinite(deadlineEpochMs) && Date.now() >= deadlineEpochMs) {
      throw new Error("Workbench backend close transaction reached its Launcher deadline before window authorization.");
    }
    if (!transaction.retryable) {
      throw new Error("Workbench backend close transaction stopped being retryable before window authorization.");
    }
    const nextPollAfterMs = Number(transaction.nextPollAfterMs);
    if (!Number.isFinite(nextPollAfterMs) || nextPollAfterMs <= 0) {
      throw new Error("Workbench backend close transaction is missing a valid Launcher-directed retry interval.");
    }
    await waitForTransactionPoll(nextPollAfterMs);
    transaction = await fetchWorkbenchCloseTransaction({ ...context, closeId: transaction.closeId });
  }
  return transaction;
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

function waitForTransactionPoll(delayMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.round(delayMs)));
}

function workbenchCloseTransactionFailureMessage(transaction: WorkbenchCloseTransaction): string {
  return String(transaction.message || transaction.failureCode || `Unexpected close transaction phase: ${transaction.phase}`);
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
      const result = await closeDesktopSession({
        ...(await resolveDesktopActionLoopContext(bootstrap)),
        revision: desktopSessionRevision
      });
      desktopSessionRevision = result.revision;
      desktopSessionRegistered = false;
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
      new URL(resolveLauncherUrl(desktopEnv, launcherBootstrap?.launcherUrl)).origin,
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
    const context = await resolveTrayLauncherControlContext();
    await postLauncherControl({
      launcherOrigin: context.launcherOrigin,
      controlToken: context.controlToken,
      path: "/api/launcher/force-stop",
      trigger: "electron_tray_stop_all"
    });
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
        void runTrayLauncherPost("/api/launcher/restart", DESKTOP_TRAY_MENU_LABELS.restartProject);
      },
      rebuildAndStart: () => {
        void runTrayLauncherPost("/api/launcher/rebuild-and-start", DESKTOP_TRAY_MENU_LABELS.rebuildAndStart);
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
      message: "Lightweight tray started without opening the Launcher window.",
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
    }
    if (desktopCliArgs.workbenchCloseCanary) {
      await windowProvider.openOrFocusWorkbench();
      return;
    }
    startDesktopActionLoop(paths, launcherBootstrap, windowProvider);
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
  const rawUrl = findVibelutionDeepLinkArg(argv);
  if (rawUrl) {
    void handlePublicDeepLinkUrl(rawUrl, "second_instance");
    return;
  }
  const secondCli = parseDesktopCliArgs(argv);
  if (secondCli.projectRoot) {
    void applyPendingProjectSlot(secondCli.projectRoot);
    return;
  }
  if (secondCli.openWorkbench) {
    requestOpenWorkbench();
    return;
  }
});

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
