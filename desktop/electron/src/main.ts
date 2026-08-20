import { BrowserWindow, Notification, app, dialog, ipcMain, nativeImage, nativeTheme, protocol } from "electron";
import { randomUUID } from "node:crypto";
import { mkdirSync, statSync, watch, writeFileSync, type FSWatcher } from "node:fs";
import { dirname, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import {
  pinSharedDesktopShellUserData,
  resolveSecondInstanceIntent,
  shouldRunDesktopWhenReadyHandlers,
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
  LauncherLifecycleSupervisor,
  type LauncherDesiredState,
  type LauncherLifecycleLease,
  type LauncherLifecycleOperation as SupervisedLifecycleOperation
} from "./lifecycle/launcherLifecycleSupervisor.js";
import {
  authorizeForceLifecycleOperation,
  type ForceLifecycleAuthorization,
  type PreconfirmedForceLifecycleAuthorization
} from "./lifecycle/forceLifecycleAuthorization.js";
import {
  DesktopLifecycleCoordinator,
  DesktopSessionMutationQueue,
  type DesktopCloseReason
} from "./lifecycle/desktopLifecycleCoordinator.js";
import { DesktopSessionMirrorQueue } from "./lifecycle/desktopSessionMirrorQueue.js";
import {
  isWorkbenchCloseControlFetchFailure,
  shouldNotifyForceStopControlFailure
} from "./lifecycle/workbenchCloseFailOpen.js";
import { appendSupervisorEventFallback } from "./lifecycle/supervisorEventFallback.js";
import { waitForWorkbenchBackendSettledForWindowClose } from "./lifecycle/workbenchBackendCloseReadiness.js";
import { readRuntimeManagerLauncherStatusSummary } from "./lifecycle/runtimeManagerStatusSnapshot.js";
import {
  createConversationNotificationService,
  type ConversationNotificationService,
  type DesktopConversationCompletionNotification,
  type DesktopConversationNotificationResult
} from "./notifications/conversationNotifications.js";
import { createDesktopPaths, resolveDesktopEntryCatalogPath, type DesktopPaths } from "./paths.js";
import { fetchLauncherControlToken, runDesktopActionOnce } from "./protocol/desktopActionClient.js";
import { planProjectSlot } from "./protocol/applyProjectSlot.js";
import {
  classifyTrayBranchInstances,
  fetchLauncherBranchInstances,
  fetchLauncherStatusSummary,
  formatLauncherStatusSummary,
  parseBranchInstanceRecords
} from "./protocol/launcherControlClient.js";
import {
  createLauncherIpcHost,
  type LauncherIpcInvokePayload,
  type OrchestratedBranchInstanceResult,
  type OrchestratedLifecycleResult
} from "./protocol/launcherIpcHost.js";
import { createLocalLauncherStatusSnapshot } from "./protocol/launcherStatusSnapshot.js";
import { createReconcileDeadlineScheduler } from "./state/reconcileDeadlineScheduler.js";
import { LauncherStateStore, type LauncherWindowTruth } from "./state/launcherStateStore.js";
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
  stopPythonLauncherService,
  type LauncherServiceStopResult
} from "./process/launcherServiceClient.js";
import {
  runWorkbenchLifecycle,
  type WorkbenchLifecycleOperation
} from "./process/workbenchLifecycle.js";
import {
  type BranchInstanceOperation
} from "./process/branchInstanceBridge.js";
import { spawnWorkbenchBackend, mainLineBackendIsReachable } from "./process/workbenchBackend.js";
import { waitForBackendHealthy } from "./process/workbenchBackendHealth.js";
import { retireRegisteredHandles } from "./process/workbenchBackendRetire.js";
import { resolveConfigHome, resolveDataHomeForProject } from "./lifecycle/projectStoragePaths.js";
import { instancesRegistryPath, recordSpawnPid } from "./lifecycle/instanceRegistryStore.js";
import {
  superviseIsolatedInstanceStart
} from "./process/isolatedInstanceSupervisor.js";
import {
  claimIsolatedStart,
  claimIsolatedStop,
  observeIsolatedError,
  observeIsolatedReady,
  renewIsolatedOwnerLease,
  resolveIsolatedClaimTarget
} from "./lifecycle/isolatedInstanceRegistryHost.js";
import {
  invalidPythonJsonBridgePayload,
  LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
  parsePythonJsonBridgePayload,
  PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
  PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS,
  PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS,
  runPythonJsonBridge
} from "./process/pythonJsonBridge.js";
import { resolveWorkbenchUrlFromBridge } from "./process/resolveWorkbenchBridge.js";
import {
  decideLauncherShellRestart,
  decidePackagedDesktopShellRefresh,
  decidePeriodicDesktopShellRefresh,
  inspectDesktopShell,
  scheduleDesktopShellRefresh,
  ensureLatestLauncher,
  shouldDeferWorkbenchOpenUntilLifecycleStart,
  shouldRefreshBeforeLifecycle,
  thenLifecycleFromDesktopCli,
  type DesktopShellStatus
} from "./process/desktopShellFreshness.js";
import {
  completeBootstrapWithoutWaitingForTelemetry,
  drainTelemetryWithDeadline,
  scheduleTelemetryWithoutWaiting,
  type LauncherBootstrapResult
} from "./process/launcherBootstrap.js";
import { assertTrustedIpcSender } from "./security/ipcSenderValidation.js";
import { isLiveWorkbenchWindowUrl } from "./security/urlPolicy.js";
import { executeApprovedDesktopShellShutdown, reapManagedRuntimeOnDesktopStart, DESKTOP_SHELL_EXIT_BUDGET_MS, DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS, withDesktopShellExitTimeout } from "./shutdown/desktopShellExit.js";
import {
  decideShutdown,
  executeShutdownAuthorizationBoundary,
  fetchLauncherActiveWorkStatus,
  resolveQuitActiveWorkStatus,
  type ActiveWorkProbeState,
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
import { createDesktopTray } from "./tray/desktopTray.js";
import {
  captureRunningInstanceIds,
  clearTrayRestartAllPending,
  readTrayRestartAllPending,
  summarizeTrayRestartAllRestore,
  writeTrayRestartAllPending,
  type TrayRestartAllRestoreResult
} from "./tray/trayRestartAllCoordinator.js";
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
    resolveLauncherWindowUrl,
  resolveWorkbenchUrl
} from "./windows/windowUrlResolver.js";
import { startOrFocusWorkbenchFromProductEntry } from "./windows/productEntryWorkbench.js";
import { waitForWorkbenchHttp, workbenchLoopbackUrl } from "./windows/workbenchHttpReady.js";
import { installBrokenPipeGuards } from "./runtime/brokenPipeGuard.js";
import {
  MainWorkbenchCloseTransactionStore,
  type MainWorkbenchCloseTransaction
} from "./lifecycle/workbenchCloseTransactionStore.js";

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
const QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS = 20_000;
const PERIODIC_SHELL_FRESHNESS_MS = 5 * 60_000;
const ACTIVE_WORK_POLICY_FORCE_INTERRUPT = true;
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
let launcherStateWatchers: FSWatcher[] = [];
let launcherStateHintTimer: ReturnType<typeof setTimeout> | null = null;
let launcherStateStatTimer: ReturnType<typeof setInterval> | null = null;
const launcherStateStatSignatures = new Map<string, string>();
const inProcessDesktopSessionStore = new InProcessDesktopSessionStore();
const mainWorkbenchCloseStore = new MainWorkbenchCloseTransactionStore();
const launcherLifecycleSupervisor = new LauncherLifecycleSupervisor();
const launcherStateStore = new LauncherStateStore(
  async () => {
    const truth = currentLauncherWindowTruth();
    const electronWindowInstanceIds = truth.instances
      .filter((item) => item.open)
      .map((item) => item.instanceId);
    if (truth.workbench?.open) {
      electronWindowInstanceIds.push("main");
    }
    const payload = await orchestrateLauncherApi("state-refresh", {
      schemaVersion: 1,
      path: "state-refresh",
      init: {
        method: "POST",
        body: { electronWindowInstanceIds }
      }
    });
    if (typeof payload !== "object" || payload === null) {
      throw new Error("launcher state refresh returned an invalid payload");
    }
    const state = payload as Record<string, unknown>;
    if (!("status" in state) || !("branchInstances" in state)) {
      throw new Error("launcher state refresh omitted required state sources");
    }
    return {
      status: state.status,
      branchInstances: state.branchInstances,
      freshness: state.freshness,
      cleanup: state.cleanup,
      nextReconcileAt: state.nextReconcileAt
    };
  },
  {
    status: createLocalLauncherStatusSnapshot(),
    branchInstances: {
      schemaVersion: 1,
      integrationRoot: "",
      branchPool: "",
      currentId: "main",
      items: []
    },
    freshness: { current: null, label: "Launcher 代码版本：未知" }
  }
);
const WORKBENCH_CLOSE_BACKEND_WAIT_MS = 30_000;
const WORKBENCH_START_READY_WAIT_MS = 90_000;
const WORKBENCH_REBUILD_READY_WAIT_MS = 300_000;
const desktopLifecycleCoordinator = new DesktopLifecycleCoordinator();
const desktopSessionMutations = new DesktopSessionMutationQueue();
const desktopSessionMirror = new DesktopSessionMirrorQueue((error: unknown) => {
  console.warn(error instanceof Error ? error.message : String(error));
});
let conversationNotificationService: ConversationNotificationService | null = null;
const desktopCliArgs = parseDesktopCliArgs(process.argv.slice(1));
let pendingOpenWorkbenchRequest = desktopCliArgs.openWorkbench;
let pendingProjectRoot = desktopCliArgs.projectRoot;
let cachedDesktopLaunchSettings: DesktopLaunchSettings | null = null;
let pendingWorkbenchCloseAck: PendingWorkbenchCloseAck | null = null;
let electronStartupStage = "electron_process_ready";
let electronStartupSummaryRecorded = false;
let workbenchOpenRequestedAtMs: number | null = null;
let trayRestartAllInFlight = false;
let trayQuitAllInFlight = false;
let trayRestartLauncherInFlight = false;
let shellRefreshInFlight = false;
let periodicShellFreshnessTimer: ReturnType<typeof setInterval> | null = null;

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
pinSharedDesktopShellUserData(app, {
  smoke: desktopCliArgs.smoke,
  workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
  env: process.env
});
const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock());
nativeTheme.themeSource = "light";
const runPrimaryWhenReady = shouldRunDesktopWhenReadyHandlers({
  lockAction: lockDecision.action,
  smoke: desktopCliArgs.smoke,
  workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary
});
if (!runPrimaryWhenReady) {
  shutdownApproved = true;
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
            return isLiveWorkbenchWindowUrl(window.webContents.getURL(), workbenchOrigin);
          } catch {
            return false;
          }
        }),
      reportState: async (state) => {
        await reportManagedWindowState(paths, bootstrap, state);
        updateLauncherWindowTruth();
      },
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
      onWorkbenchOpenRequest: () => startOrFocusWorkbenchFromProductEntryOnShell(),
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

function currentLauncherWindowTruth(): LauncherWindowTruth {
  const provider = windowProvider;
  const snapshot = provider?.snapshot();
  return {
    workbench: snapshot
      ? {
          open: snapshot.workbench.open === true,
          rendererProcessId: snapshot.workbench.rendererProcessId
        }
      : null,
    instances: provider ? provider.instanceWindowStates() : []
  };
}

function updateLauncherWindowTruth(): void {
  launcherStateStore.updateWindowTruth(currentLauncherWindowTruth());
}

const reconcileDeadlineScheduler = createReconcileDeadlineScheduler({
  onDue: () => {
    void launcherStateStore.refresh("reconcile_deadline");
  }
});

launcherStateStore.subscribe((snapshot) => {
  reconcileDeadlineScheduler.schedule(snapshot.nextReconcileAt);
  windowProvider?.sendToLauncher(IPC_CHANNELS.launcherStateChanged, snapshot);
});

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

async function bootstrapMainOwnedLauncher(paths: DesktopPaths): Promise<LauncherBootstrapResult | null> {
  // T9: Electron main is the Launcher control plane. The Python :8765 service
  // is no longer spawned; the workbench URL is resolved through a no-console
  // Python bridge (env → ports.json → config → default).
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  electronStartupStage = "control_plane_attach";
  const stageStartedAtMs = performance.now();
  let workbenchUrl = "";
  if (pythonPath) {
    try {
      workbenchUrl = await resolveWorkbenchUrlFromBridge({
        workspaceRoot: paths.workspaceRoot,
        pythonPath,
        operatorConfigPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim()
      });
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    }
  }
  workbenchUrl = resolveWorkbenchUrl(desktopEnv, workbenchUrl || undefined);
  const bootstrapIdentity = `electron-${process.pid}-${Date.now().toString(36)}`;
  const result: LauncherBootstrapResult = {
    schemaVersion: 1,
    workspaceRoot: paths.workspaceRoot,
    operatorConfigPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
    workspaceId: "electron-main",
    launcherInstanceId: bootstrapIdentity,
    mode: "attached",
    launcherBackendPid: 0,
    launcherUrl: workbenchUrl,
    workbenchUrl,
    ready: true,
    protocolVersion: 1,
    minDesktopProtocolVersion: 1,
    maxDesktopProtocolVersion: 1,
    capabilities: [
      "desktop_actions.claim",
      "desktop_sessions.heartbeat",
      "runtime_scene.electron_event",
      "workbench_close.transaction.v1"
    ]
  };
  const event = {
    eventCode: "electron.startup.control_plane_attached",
    message: "Electron main is the Launcher control plane.",
    fields: electronStartupFields({
      stage: "control_plane_attach",
      stageDurationMs: electronStageElapsedMs(stageStartedAtMs),
      mode: "main_orchestrated",
      launcherBackendPid: 0
    })
  };
  return completeBootstrapWithoutWaitingForTelemetry(result, () => recordElectronSupervisorEvent(result, event));
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
      void desktopSessionMirror.register(() => registerDesktopSession({
        ...context,
        workspaceRoot: paths.workspaceRoot,
        capabilities: desktopSessionCapabilities(bootstrap)
      })).catch(() => undefined);
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
    void desktopSessionMirror.mutate("window", (mirrorRevision) => reportDesktopWindowState({
      ...context,
      role: state.role,
      revision: mirrorRevision,
      state
    })).catch(() => undefined);
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
        await desktopSessionMirror.mutate("heartbeat", (mirrorRevision) => heartbeatDesktopSession({
          ...context,
          revision: mirrorRevision
        }));
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
  const launcherOrigin = resolveWorkbenchUrl(desktopEnv, bootstrap.workbenchUrl);
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
    recordSupervisorEventFallbackLocally(event);
    return;
  }
  try {
    const bridge = await resolveRuntimeSceneBridge(bootstrap);
    await bridge.record(event);
  } catch (error: unknown) {
    recordSupervisorEventFallbackLocally(event, error);
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

let supervisorEventFallbackWorkspaceRoot: string | null | undefined;

function recordSupervisorEventFallbackLocally(
  event: RuntimeSceneElectronEvent,
  error?: unknown
): void {
  if (supervisorEventFallbackWorkspaceRoot === undefined) {
    try {
      supervisorEventFallbackWorkspaceRoot = createDesktopPathsForApp().workspaceRoot;
    } catch {
      supervisorEventFallbackWorkspaceRoot = null;
    }
  }
  const workspaceRoot = supervisorEventFallbackWorkspaceRoot;
  if (workspaceRoot === null) {
    console.warn(`supervisor event ${event.eventCode} lost: no workspace root for local fallback`);
    return;
  }
  const recorded = appendSupervisorEventFallback(workspaceRoot, {
    eventCode: event.eventCode,
    message: event.message,
    fields: {
      ...event.fields,
      ...(error === undefined ? {} : { fallbackReason: error instanceof Error ? error.message : String(error) })
    }
  });
  if (!recorded) {
    console.warn(`supervisor event ${event.eventCode} lost: local fallback write failed`);
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
    let activeWorkState: ActiveWorkProbeState = "unknown";
    try {
      const status = await withDesktopShellExitTimeout(
        fetchLauncherActiveWorkStatus(context),
        ACTIVE_WORK_STATUS_TIMEOUT_MS,
        "resolve launcher active work status for workbench close"
      );
      activeWorkState = status.state;
    } catch {
      activeWorkState = "unknown";
    }
    let transaction = mainWorkbenchCloseStore.submit({
      mode: "normal",
      reason: "workbench_window_close",
      activeWorkState
    });
    if (transaction.phase === "confirmation_required") {
      const confirmed = await confirmWorkbenchForceClose(provider, transaction.activeWorkState);
      if (!confirmed) {
        await recordElectronSupervisorEvent(bootstrap, {
          eventCode: "electron.workbench_close.cancelled_active_work",
          message: "Workbench close was cancelled while active work was present.",
          fields: {
            closeId: transaction.closeId,
            requestId: transaction.requestId ?? "",
            desktopSessionId: context.desktopSessionId,
            operatorIntent: "keep_running",
            activeWorkState: transaction.activeWorkState
          }
        });
        return;
      }
      transaction = mainWorkbenchCloseStore.confirm(transaction.closeId, transaction.requestId!);
    }
    pendingWorkbenchCloseAck = {
      closeId: transaction.closeId,
      desktopSessionId: context.desktopSessionId
    };
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.backend_stopping",
      message: "Electron is stopping the workbench backend.",
      fields: {
        closeId: transaction.closeId,
        requestId: transaction.requestId ?? "",
        desktopSessionId: context.desktopSessionId,
        operatorIntent: transaction.mode === "force" ? "force_close" : "close",
        activeWorkState: transaction.activeWorkState,
        mode: transaction.mode
      }
    });
    await stopWorkbenchBackend(paths, bootstrap, transaction);
    const backendStopped = await waitForWorkbenchBackendSettledForWindowClose({
      readStatus: async () => {
        try {
          return await fetchLauncherStatusSummary(context);
        } catch {
          return readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot);
        }
      },
      timeoutMs: WORKBENCH_CLOSE_BACKEND_WAIT_MS
    });
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
  bootstrap: LauncherBootstrapResult,
  transaction: MainWorkbenchCloseTransaction
): Promise<void> {
  void paths;
  void bootstrap;
  const operation = transaction.mode === "force" ? "force-stop" : "stop";
  const result = await orchestrateLauncherLifecycle(operation, {
    schemaVersion: 1,
    path: operation,
    init: {
      method: "POST",
      body: {
        requestId: transaction.requestId,
        closeId: transaction.closeId,
        deferWindowClose: true,
        confirmed: transaction.mode === "force",
        operatorIntent: transaction.mode === "force" ? "force_close" : "close",
        activeWorkState: transaction.activeWorkState
      }
    }
  });
  if (!result.accepted) {
    throw new Error(result.message || result.code || `Workbench ${operation} was not accepted.`);
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
    if (pending === null) {
      // A workbench window closed outside any close transaction (shutdown
      // approved, authorized leftover, or a bypassed intercept). The backend
      // keeps running in that case and Launcher will sit on 部分运行 with no
      // trace unless this is recorded.
      await recordElectronSupervisorEvent(bootstrap, {
        eventCode: "electron.workbench_close.untracked_window_closed",
        message: "Workbench window closed without a close transaction; the backend may keep running.",
        fields: {
          shutdownApproved,
          workspaceRoot: paths.workspaceRoot
        }
      });
    }
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
    await recordElectronSupervisorEvent(bootstrap, {
      eventCode: "electron.workbench_close.fail_open_user_declined",
      message: "Workbench close transaction failed and retry was declined; closing the window while the backend may keep running.",
      fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
    });
    await provider.approveWorkbenchCloseOnce();
    return;
  }
  setTimeout(() => {
    void requestTransactionalWorkbenchClose(paths, bootstrap).catch((retryError: unknown) =>
      handleTransactionalWorkbenchCloseFailure(paths, bootstrap, retryError)
    );
  }, 0);
}

async function confirmWorkbenchForceClose(
  provider: ElectronWindowProvider,
  activeWorkState: ActiveWorkProbeState
): Promise<boolean> {
  const statusUnknown = activeWorkState === "unknown";
  const options = {
    type: "warning" as const,
    title: statusUnknown ? "无法确认任务状态" : "仍有进行中的任务",
    message: statusUnknown
      ? "当前无法确认是否有任务运行，强制关闭可能中断任务。"
      : "关闭工作台会中断正在运行的任务。",
    detail: "选择“继续运行”会保留窗口、后端和当前任务；只有再次确认才会强制关闭。",
    buttons: ["继续运行", "停止任务并关闭"],
    defaultId: 0,
    cancelId: 0,
    noLink: true
  };
  const parent = provider.workbenchDialogParent() as unknown as BrowserWindow | null;
  const response = parent === null ? await dialog.showMessageBox(options) : await dialog.showMessageBox(parent, options);
  return response.response === 1;
}

function launcherLifecyclePayloadBody(payload: LauncherIpcInvokePayload): Record<string, unknown> {
  const body = payload.init?.body;
  return typeof body === "object" && body !== null && !Array.isArray(body)
    ? body as Record<string, unknown>
    : {};
}

function preconfirmedCloseAuthorization(
  instanceId: string,
  payload: LauncherIpcInvokePayload
): PreconfirmedForceLifecycleAuthorization | undefined {
  if (instanceId !== "main") {
    return undefined;
  }
  const body = launcherLifecyclePayloadBody(payload);
  const requestId = String(body.requestId ?? "").trim();
  const transaction = mainWorkbenchCloseStore.currentTransaction();
  if (
    !requestId
    || transaction === null
    || transaction.phase !== "backend_closing"
    || transaction.mode !== "force"
    || transaction.requestId !== requestId
  ) {
    return undefined;
  }
  return {
    requestId,
    probeState: transaction.activeWorkState,
    probeMessage: `Workbench close transaction observed ${transaction.activeWorkState} active-work state.`
  };
}

async function confirmLauncherForceLifecycle(
  authorization: ForceLifecycleAuthorization
): Promise<boolean> {
  const stateDetail = authorization.probeState === "active"
    ? "检测到进行中的任务。"
    : authorization.probeState === "unknown"
      ? "当前无法确认是否有任务运行。"
      : "当前未检测到活动任务，但强制操作仍可能中断正在收口的进程。";
  const options = {
    type: "warning" as const,
    title: "确认强制停止",
    message: `${stateDetail} 是否继续强制停止 ${authorization.instanceId === "main" ? "主工作台" : "隔离实例"}？`,
    detail: `请求 ${authorization.requestId}。取消会保留当前窗口、运行时和任务。`,
    buttons: ["取消", "确认强制停止"],
    defaultId: 0,
    cancelId: 0,
    noLink: true
  };
  const parent = windowProvider?.workbenchDialogParent() as unknown as BrowserWindow | null | undefined;
  const response = parent
    ? await dialog.showMessageBox(parent, options)
    : await dialog.showMessageBox(options);
  return response.response === 1;
}

async function authorizeLauncherForceLifecycle(input: {
  operation: string;
  instanceId: string;
  payload: LauncherIpcInvokePayload;
  operatorIntent: string;
}): Promise<ForceLifecycleAuthorization | null> {
  const body = launcherLifecyclePayloadBody(input.payload);
  const operatorIntent = String(body.operatorIntent ?? input.operatorIntent).trim() || input.operation;
  return await authorizeForceLifecycleOperation({
    operation: input.operation,
    instanceId: input.instanceId,
    operatorIntent,
    preconfirmed: preconfirmedCloseAuthorization(input.instanceId, input.payload),
    probe: async () => {
      if (input.instanceId !== "main") {
        return {
          state: "unknown",
          message: "isolated instance active-work projection is unavailable before force authorization"
        };
      }
      if (launcherBootstrap === null) {
        return { state: "unknown", message: "Launcher bootstrap is not available." };
      }
      const context = await resolveDesktopActionLoopContext(launcherBootstrap);
      return await withDesktopShellExitTimeout(
        fetchLauncherActiveWorkStatus(context),
        ACTIVE_WORK_STATUS_TIMEOUT_MS,
        "resolve launcher active work for force authorization"
      );
    },
    confirm: confirmLauncherForceLifecycle,
    record: async (authorization) => {
      await recordElectronSupervisorEvent(launcherBootstrap, {
        eventCode: "electron.lifecycle.force_authorized",
        message: "Operator confirmed a force Launcher lifecycle operation.",
        fields: {
          requestId: authorization.requestId,
          instanceId: authorization.instanceId,
          operation: authorization.operation,
          operatorIntent: authorization.operatorIntent,
          activeWorkState: authorization.probeState,
          activeWorkMessage: authorization.probeMessage.slice(0, 300)
        }
      });
    }
  });
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
      await desktopSessionMirror.mutate("close", (mirrorRevision) => closeDesktopSession({
        ...context,
        revision: mirrorRevision
      }));
    });
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

async function stopOwnedPythonLauncherService(): Promise<LauncherServiceStopResult> {
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to stop the leftover Launcher Service");
  }
  const paths = createDesktopPathsForApp();
  const workspaceRoot = launcherBootstrap?.workspaceRoot || paths.workspaceRoot;
  const operatorConfigPath =
    launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim();
  return await stopPythonLauncherService({
    workspaceRoot,
    pythonPath,
    operatorConfigPath,
    launcherBackendPid: launcherBootstrap?.launcherBackendPid ?? 0
  });
}

async function stopManagedRuntime(): Promise<void> {
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to stop managed project processes");
  }
  const paths = createDesktopPathsForApp();
  const lease = launcherLifecycleSupervisor.beginIntent({
    instanceId: "main",
    operation: "shutdown",
    desiredState: "closed"
  });
  const mutation = await launcherLifecycleSupervisor.executeMutation({
    lease,
    mutate: async () => await runWorkbenchLifecycle({
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
      operation: "shutdown",
      signal: lease.signal
    }),
    reconcile: async () => {
      scheduleLauncherStatusCliRefresh();
    }
  });
  if (mutation.outcome === "failed") {
    throw mutation.error;
  }
  if (mutation.outcome === "uncertain") {
    throw new Error("Managed runtime shutdown outcome is uncertain; reconciliation started.");
  }
  if (mutation.outcome === "ignored" || mutation.outcome === "superseded") {
    return;
  }
  if (!mutation.value.accepted) {
    throw new Error(mutation.value.message || mutation.value.code || "Managed runtime shutdown was not accepted.");
  }
}

function desktopPythonPath(): string {
  const desktopEnv = desktopEnvironment();
  return String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
}

async function inspectCurrentDesktopShell(): Promise<DesktopShellStatus> {
  const pythonPath = desktopPythonPath();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to inspect the desktop shell");
  }
  const paths = createDesktopPathsForApp();
  return await inspectDesktopShell({
    workspaceRoot: paths.workspaceRoot,
    pythonPath
  });
}

async function scheduleCurrentDesktopShellRefresh(
  thenLifecycle: string,
  options: { force?: boolean } = {}
): Promise<void> {
  const pythonPath = desktopPythonPath();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to refresh the desktop shell");
  }
  const paths = createDesktopPathsForApp();
  const scheduled = await scheduleDesktopShellRefresh({
    workspaceRoot: paths.workspaceRoot,
    pythonPath,
    waitPid: process.pid,
    thenLifecycle,
    force: options.force === true
  });
  if (!scheduled.scheduled || scheduled.helperPid <= 0) {
    const reason = scheduled.reason ? ` (${scheduled.reason})` : "";
    throw new Error(`desktop shell refresh helper did not start${reason}`);
  }
}

async function refreshPackagedDesktopShellIfStale(thenLifecycle: string): Promise<boolean> {
  if (
    decidePackagedDesktopShellRefresh({
      isPackaged: app.isPackaged,
      smoke: desktopCliArgs.smoke,
      workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
      stale: true,
      refreshBlocked: false
    }) !== "refresh"
  ) {
    return false;
  }
  let status: DesktopShellStatus;
  try {
    status = await inspectCurrentDesktopShell();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `检查桌面壳版本失败，继续使用当前壳：${detail.slice(0, 220)}`, "warning");
    return false;
  }
  if (status.refreshBlocked) {
    const detail = String(status.refreshBlockedDetail || status.refreshBlockedReason || "recent refresh failure").slice(0, 180);
    notifyDesktopTray(
      "Vibelution",
      `桌面壳自动更新已暂停，继续使用当前壳：${detail}。可在托盘使用「全部重启」重试。`,
      "warning"
    );
    return false;
  }
  if (
    decidePackagedDesktopShellRefresh({
      isPackaged: app.isPackaged,
      smoke: desktopCliArgs.smoke,
      workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
      stale: status.stale,
      refreshBlocked: status.refreshBlocked
    }) !== "refresh"
  ) {
    return false;
  }
  notifyDesktopTray("Vibelution", "桌面壳不是当前代码，Launcher 正在自行更新…");
  shellRefreshInFlight = true;
  try {
    await scheduleCurrentDesktopShellRefresh(thenLifecycle);
  } catch (error: unknown) {
    shellRefreshInFlight = false;
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `无法安排桌面壳更新：${detail.slice(0, 220)}`, "warning");
    return false;
  }
  try {
    await stopManagedRuntime();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止托管项目进程失败，仍将退出以便更新：${detail.slice(0, 220)}`, "warning");
  }
  shutdownApproved = true;
  app.exit(0);
  return true;
}

async function runSmokeAndQuit(paths: DesktopPaths): Promise<void> {
  const desktopEnv = desktopEnvironment();
  const bootstrap = await resolveSmokeBootstrap(paths, desktopEnv);
  launcherBootstrap = bootstrap.result;
  const launcherUrl = resolveLauncherWindowUrl(desktopEnv);
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
    stopManagedRuntime,
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
    const result = await bootstrapMainOwnedLauncher(paths);
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

async function stopMainRuntimeForApprovedShutdown(): Promise<void> {
  const result = await orchestrateLauncherLifecycle("shutdown", {
    schemaVersion: 1,
    path: "desktop-shell-shutdown",
    init: {
      method: "POST",
      body: { operatorIntent: "desktop_shell_shutdown" }
    }
  });
  if (!result.accepted) {
    throw new Error(result.message || result.code || "Launcher shutdown was not accepted.");
  }
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
          const bootstrap = launcherBootstrap;
          if (bootstrap === null) {
            return { state: "unknown", message: "Launcher bootstrap is not available." };
          }
          const probeQuitActiveWork = async (forceControlTokenRefresh: boolean) => {
            const context = await resolveDesktopActionLoopContext(bootstrap, {
              forceControlTokenRefresh
            });
            return await withDesktopShellExitTimeout(
              fetchLauncherActiveWorkStatus(context),
              QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS,
              "resolve launcher active work status for quit"
            );
          };
          return await resolveQuitActiveWorkStatus({
            probe: () => probeQuitActiveWork(false),
            recoverAndRetry: () => probeQuitActiveWork(true)
          });
        }
      }),
      onDenied: (decision) => {
        notifyDesktopTray("Vibelution", decision.message || "有进行中的任务，暂时无法退出。可先用托盘“退出壳并停止全部任务”。", "warning");
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
            stopManagedRuntime: stopMainRuntimeForApprovedShutdown,
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
        // Best-effort stop managed runtime and owned Python before force quit so orphans are less likely.
        try {
          await withDesktopShellExitTimeout(
            stopMainRuntimeForApprovedShutdown(),
            Math.min(3_000, DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS),
            "stop managed runtime on exit budget fail-open"
          );
        } catch {
          // Fail-open: stop must not block the forced Electron quit.
        }
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
      launcherOrigin: resolveWorkbenchUrl(desktopEnvironment(), launcherBootstrap?.workbenchUrl),
      controlToken: ""
    };
  }
}

async function resolveInterruptedActiveWorkCount(): Promise<number> {
  if (launcherBootstrap === null) {
    return 0;
  }
  try {
    const context = await resolveDesktopActionLoopContext(launcherBootstrap);
    const status = await withDesktopShellExitTimeout(
      fetchLauncherActiveWorkStatus(context),
      ACTIVE_WORK_STATUS_TIMEOUT_MS,
      "resolve launcher active work for tray force action"
    );
    return status.state === "active" ? 1 : 0;
  } catch {
    return 0;
  }
}

async function recordTrayForceInterruptEvidence(eventCode: string, message: string, fields: Record<string, string | number | boolean>): Promise<void> {
  await recordElectronSupervisorEvent(launcherBootstrap, {
    eventCode,
    message,
    fields: {
      activeWorkPolicy: "FORCE_INTERRUPT",
      ...fields
    }
  }).catch(() => undefined);
}

async function stopAllManagedRuntimeTrees(): Promise<void> {
  try {
    await orchestrateLauncherLifecycle("force-stop", { schemaVersion: 1, path: "force-stop" });
    await new Promise((resolve) => setTimeout(resolve, 1500));
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止托管运行时失败，仍将重启 Launcher：${detail.slice(0, 220)}`, "warning");
  }
  try {
    await stopManagedRuntime();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止托管项目进程失败，仍将重启 Launcher：${detail.slice(0, 220)}`, "warning");
  }
  try {
    await stopOwnedPythonLauncherService();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `停止 Launcher 后端失败，仍将重启：${detail.slice(0, 220)}`, "warning");
  }
  const provider = windowProvider;
  if (provider !== null) {
    try {
      await provider.approveWorkbenchCloseOnce();
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    }
  }
}

async function exitAndRelaunchLauncherShell(options: { forceShellRefresh?: boolean } = {}): Promise<void> {
  const forceRefresh = options.forceShellRefresh === true;
  let stale = false;
  if (app.isPackaged) {
    try {
      stale = (await inspectCurrentDesktopShell()).stale;
    } catch {
      stale = false;
    }
  }
  const decision = decideLauncherShellRestart({
    isPackaged: app.isPackaged,
    stale,
    forceRefresh
  });
  if (decision === "rebuild-and-exit") {
    shellRefreshInFlight = true;
    try {
      await scheduleCurrentDesktopShellRefresh("", { force: forceRefresh });
    } catch (error: unknown) {
      shellRefreshInFlight = false;
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法安排桌面壳更新，继续使用当前壳重启：${detail.slice(0, 220)}`, "warning");
      app.relaunch();
      shutdownApproved = true;
      app.exit(0);
      return;
    }
    shutdownApproved = true;
    app.exit(0);
    return;
  }
  if (decision === "ensure-and-relaunch") {
    notifyDesktopTray("Vibelution", "正在构建最新 Launcher…");
    try {
      const pythonPath = desktopPythonPath();
      if (!pythonPath) {
        throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to ensure the latest launcher");
      }
      await ensureLatestLauncher({
        workspaceRoot: createDesktopPathsForApp().workspaceRoot,
        pythonPath
      });
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法重建最新前端，仍将重启当前壳：${detail.slice(0, 220)}`, "warning");
    }
  }
  app.relaunch();
  shutdownApproved = true;
  app.exit(0);
}

async function runTrayRestartLauncher(): Promise<void> {
  if (trayRestartLauncherInFlight || trayRestartAllInFlight || trayQuitAllInFlight || shellRefreshInFlight) {
    notifyDesktopTray("Vibelution", "已有托盘操作进行中，请稍候。", "warning");
    return;
  }
  trayRestartLauncherInFlight = true;
  const paths = createDesktopPathsForApp();
  try {
    const interruptedActiveWorkCount = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
      ? await resolveInterruptedActiveWorkCount()
      : 0;
    if (interruptedActiveWorkCount > 0) {
      await recordTrayForceInterruptEvidence("electron.tray.restart_launcher.force_interrupt", "Tray restart-launcher proceeding while active work was present.", {
        interruptedActiveWorkCount
      });
    }
    clearTrayRestartAllPending(paths.workspaceRoot);
    notifyDesktopTray("Vibelution", "正在全部停止并启动最新 Launcher…");
    await stopAllManagedRuntimeTrees();
    await exitAndRelaunchLauncherShell({ forceShellRefresh: true });
  } finally {
    trayRestartLauncherInFlight = false;
  }
}

async function restoreTrayRestartAllPending(workspaceRoot: string): Promise<TrayRestartAllRestoreResult> {
  const pending = readTrayRestartAllPending(workspaceRoot);
  if (pending === null) {
    return { restored: [], failed: [], skipped: [] };
  }
  clearTrayRestartAllPending(workspaceRoot);
  const result: TrayRestartAllRestoreResult = { restored: [], failed: [], skipped: [] };
  if (!pending.instanceIds.length) {
    return result;
  }
  for (const instanceId of pending.instanceIds) {
    try {
      if (instanceId === "main") {
        const lifecycle = await orchestrateLauncherLifecycle("start", {
          schemaVersion: 1,
          path: "tray-restart-all-restore"
        });
        if (!lifecycle.accepted) {
          result.failed.push({
            instanceId,
            message: String(lifecycle.message || lifecycle.code || "main 启动未受理")
          });
          continue;
        }
      } else {
        const branch = await orchestrateBranchInstanceLifecycle("start", {
          schemaVersion: 1,
          path: "branch-instances/start",
          init: {
            method: "POST",
            body: { instanceId }
          }
        });
        if (!branch.accepted) {
          result.failed.push({
            instanceId,
            message: String(branch.message || branch.code || "隔离实例启动未受理")
          });
          continue;
        }
      }
      result.restored.push(instanceId);
    } catch (error: unknown) {
      result.failed.push({
        instanceId,
        message: error instanceof Error ? error.message.slice(0, 220) : String(error)
      });
    }
  }
  await recordTrayForceInterruptEvidence("electron.tray.restart_all.restore", "Tray restart-all restore completed.", {
    restoredCount: result.restored.length,
    failedCount: result.failed.length,
    interruptedActiveWorkCount: pending.interruptedActiveWorkCount
  });
  return result;
}

async function maybeRestoreTrayRestartAllPending(): Promise<void> {
  const paths = createDesktopPathsForApp();
  const pending = readTrayRestartAllPending(paths.workspaceRoot);
  if (pending === null) {
    return;
  }
  const restore = await restoreTrayRestartAllPending(paths.workspaceRoot);
  notifyDesktopTray("Vibelution", summarizeTrayRestartAllRestore(restore), restore.failed.length ? "warning" : "info");
  if (restore.failed.length) {
    for (const failure of restore.failed.slice(0, 3)) {
      await recordTrayForceInterruptEvidence("electron.tray.restart_all.restore_failed", "Tray restart-all instance restore failed.", {
        instanceId: failure.instanceId,
        message: failure.message.slice(0, 220)
      });
    }
  }
  if (app.isPackaged) {
    try {
      const status = await inspectCurrentDesktopShell();
      if (status.stale) {
        notifyDesktopTray("Vibelution", `桌面壳更新后仍判定过期（${status.reason}），请查看 runtime 证据。`, "warning");
        await recordTrayForceInterruptEvidence("electron.tray.restart_all.post_refresh_stale", "Desktop shell remained stale after tray restart-all refresh.", {
          reason: status.reason
        });
      }
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法二次验证桌面壳版本：${detail.slice(0, 220)}`, "warning");
    }
  }
}

async function runTrayRestartAll(): Promise<void> {
  if (trayRestartAllInFlight || trayQuitAllInFlight || trayRestartLauncherInFlight || shellRefreshInFlight) {
    notifyDesktopTray("Vibelution", "已有托盘操作进行中，请稍候。", "warning");
    return;
  }
  trayRestartAllInFlight = true;
  const paths = createDesktopPathsForApp();
  try {
    const interruptedActiveWorkCount = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
      ? await resolveInterruptedActiveWorkCount()
      : 0;
    if (interruptedActiveWorkCount > 0) {
      await recordTrayForceInterruptEvidence("electron.tray.restart_all.force_interrupt", "Tray restart-all proceeding while active work was present.", {
        interruptedActiveWorkCount
      });
    }
    let runningInstanceIds: string[] = [];
    try {
      runningInstanceIds = captureRunningInstanceIds(
        await fetchLauncherBranchInstances({
          ...(await resolveTrayControlContextOrLoopback()),
          requestTimeoutMs: 20_000
        })
      );
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法读取运行集合，已取消全部重启：${detail.slice(0, 220)}`, "warning");
      return;
    }
    let stale = false;
    if (app.isPackaged) {
      try {
        stale = (await inspectCurrentDesktopShell()).stale;
      } catch (error: unknown) {
        const detail = error instanceof Error ? error.message : String(error);
        notifyDesktopTray("Vibelution", `检查桌面壳版本失败，继续使用当前壳：${detail.slice(0, 220)}`, "warning");
      }
    }
    writeTrayRestartAllPending(paths.workspaceRoot, {
      instanceIds: runningInstanceIds,
      interruptedActiveWorkCount,
      shellRefreshScheduled: false
    });
    notifyDesktopTray("Vibelution", "正在全部重启…");
    await stopAllManagedRuntimeTrees();
    if (app.isPackaged && stale) {
      shellRefreshInFlight = true;
      writeTrayRestartAllPending(paths.workspaceRoot, {
        instanceIds: runningInstanceIds,
        interruptedActiveWorkCount,
        shellRefreshScheduled: true
      });
      try {
        await scheduleCurrentDesktopShellRefresh("", { force: true });
      } catch (error: unknown) {
        shellRefreshInFlight = false;
        const detail = error instanceof Error ? error.message : String(error);
        notifyDesktopTray("Vibelution", `无法安排桌面壳更新：${detail.slice(0, 220)}`, "warning");
        clearTrayRestartAllPending(paths.workspaceRoot);
        return;
      }
      shutdownApproved = true;
      app.exit(0);
      return;
    }
    await exitAndRelaunchLauncherShell({ forceShellRefresh: true });
  } finally {
    trayRestartAllInFlight = false;
  }
}

async function requestForcedDesktopShellExit(
  closeReason: DesktopCloseReason = "desktop_shell_quit"
): Promise<void> {
  if (trayQuitAllInFlight || trayRestartAllInFlight || trayRestartLauncherInFlight) {
    notifyDesktopTray("Vibelution", "已有托盘操作进行中，请稍候。", "warning");
    return;
  }
  trayQuitAllInFlight = true;
  try {
    return await desktopLifecycleCoordinator.request(closeReason, async () => {
      const ownershipMode = launcherBootstrap?.mode ?? "attached";
      const interruptedActiveWorkCount = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
        ? await resolveInterruptedActiveWorkCount()
        : 0;
      if (interruptedActiveWorkCount > 0) {
        await recordTrayForceInterruptEvidence("electron.tray.quit_all.force_interrupt", "Tray quit-all proceeding while active work was present.", {
          interruptedActiveWorkCount
        });
      }
      try {
        await orchestrateLauncherLifecycle("force-stop", { schemaVersion: 1, path: "force-stop" });
        await new Promise((resolve) => setTimeout(resolve, 1500));
      } catch (error: unknown) {
        if (shouldNotifyForceStopControlFailure(error)) {
          const detail = error instanceof Error ? error.message : String(error);
          notifyDesktopTray("Vibelution", `停止托管运行时失败：${detail.slice(0, 220)}`, "warning");
        }
      }
      pendingWorkbenchCloseAck = null;
      await withDesktopShellExitTimeout(
        executeApprovedDesktopShellShutdown({
          decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: true },
          closeDesktopSession: closeDesktopSessionIfRegistered,
          recordEvent: async (event) => {
            await recordElectronSupervisorEvent(launcherBootstrap, {
              ...event,
              fields: {
                closeReason,
                ownershipMode,
                forced: true,
                interruptedActiveWorkCount,
                ...(event.fields ?? {})
              }
            });
          },
          stopManagedRuntime,
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
        "forced desktop shell exit"
      );
    });
  } finally {
    trayQuitAllInFlight = false;
  }
}

async function runTrayQuitAll(): Promise<void> {
  try {
    await requestForcedDesktopShellExit("desktop_shell_quit");
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
}

function startPeriodicShellFreshnessWatch(): void {
  if (periodicShellFreshnessTimer !== null) {
    return;
  }
  periodicShellFreshnessTimer = setInterval(() => {
    void (async () => {
      if (
        decidePeriodicDesktopShellRefresh({
          isPackaged: app.isPackaged,
          smoke: desktopCliArgs.smoke,
          workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
          stale: false,
          refreshInFlight: shellRefreshInFlight || trayRestartAllInFlight || trayQuitAllInFlight || trayRestartLauncherInFlight,
          shutdownApproved
        }) !== "refresh"
      ) {
        return;
      }
      let status: DesktopShellStatus | null = null;
      try {
        status = await inspectCurrentDesktopShell();
      } catch {
        return;
      }
      if (
        decidePeriodicDesktopShellRefresh({
          isPackaged: app.isPackaged,
          smoke: desktopCliArgs.smoke,
          workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
          stale: status.stale,
          refreshInFlight: shellRefreshInFlight || trayRestartAllInFlight || trayQuitAllInFlight || trayRestartLauncherInFlight,
          shutdownApproved,
          refreshBlocked: status.refreshBlocked
        }) !== "refresh"
      ) {
        return;
      }
      shellRefreshInFlight = true;
      notifyDesktopTray("Vibelution", "检测到桌面壳过期，正在无控制台更新…");
      const refreshed = await refreshPackagedDesktopShellIfStale("");
      if (!refreshed) {
        shellRefreshInFlight = false;
      }
    })().catch((error: unknown) => {
      shellRefreshInFlight = false;
      console.warn(error instanceof Error ? error.message : String(error));
    });
  }, PERIODIC_SHELL_FRESHNESS_MS);
  void periodicShellFreshnessTimer;
}

async function runTrayBranchInstance(operation: string, instanceId: string, label: string): Promise<void> {
  try {
    await orchestrateBranchInstanceLifecycle(operation, {
      schemaVersion: 1,
      path: `branch-instances/${operation}`,
      init: {
        method: "POST",
        body: { instanceId }
      }
    });
    notifyDesktopTray("Vibelution", `${label}请求已发送。`);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `${label}失败：${detail.slice(0, 300)}`, "warning");
  }
}

async function runTrayStopAll(): Promise<void> {
  try {
    await requestForcedDesktopShellExit("desktop_shell_quit");
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
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
  payload: LauncherIpcInvokePayload
): Promise<OrchestratedLifecycleResult> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  const forceAuthorization = await authorizeLauncherForceLifecycle({
    operation,
    instanceId: "main",
    payload,
    operatorIntent: payload.path || operation
  });
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to orchestrate the workbench lifecycle");
  }
  const supervisedOperation = normalizeSupervisedLifecycleOperation(operation);
  const desiredState = desiredStateForLifecycleOperation(supervisedOperation);
  const paths = createDesktopPathsForApp();
  if (supervisedOperation === "start" && windowProvider !== null) {
    if (await mainLineBackendIsReachable(paths.workspaceRoot)) {
      const url = await refreshLiveWorkbenchUrl(paths);
      await openWorkbenchAtCurrentLauncherUrl(paths, launcherBootstrap, windowProvider, { workbenchUrl: url });
      scheduleLauncherStatusCliRefresh();
      return {
        schemaVersion: 1,
        accepted: true,
        operation,
        ...(forceAuthorization ? { requestId: forceAuthorization.requestId } : {}),
        message: "已打开工作台窗口。"
      };
    }
  }
  const intentLease = launcherLifecycleSupervisor.beginIntent({
    instanceId: "main",
    operation: supervisedOperation,
    desiredState
  });
  if (app.isPackaged) {
    try {
      const status = await inspectCurrentDesktopShell();
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      if (shouldRefreshBeforeLifecycle(operation, { isPackaged: true, stale: status.stale })) {
        notifyDesktopTray("Vibelution", "桌面壳不是当前代码，Launcher 正在自行更新后再执行…");
        await scheduleCurrentDesktopShellRefresh(operation);
        if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
          return supersededLifecycleResult(operation);
        }
        try {
          await stopManagedRuntime();
        } catch (error: unknown) {
          const detail = error instanceof Error ? error.message : String(error);
          notifyDesktopTray("Vibelution", `停止托管项目进程失败，仍将退出以便更新：${detail.slice(0, 220)}`, "warning");
        }
        shutdownApproved = true;
        app.exit(0);
        return {
          schemaVersion: 1,
          accepted: true,
          operation,
          message: "desktop shell refresh scheduled"
        };
      }
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    }
  }
  const mutation = await launcherLifecycleSupervisor.executeMutation({
    lease: intentLease,
    mutate: async () => await runWorkbenchLifecycle({
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
      operation: operation as WorkbenchLifecycleOperation,
      signal: intentLease.signal
    }),
    reconcile: async () => {
      scheduleLauncherStatusCliRefresh();
    }
  });
  if (mutation.outcome === "failed") {
    throw mutation.error;
  }
  if (mutation.outcome === "uncertain") {
    throw new Error(`Launcher lifecycle ${operation} outcome is uncertain; reconciliation started.`);
  }
  if (mutation.outcome === "ignored") {
    return supersededLifecycleResult(operation);
  }
  const result = mutation.value;
  if (mutation.outcome === "superseded") {
    return supersededLifecycleResult(operation, result.commandId);
  }
  const lease = result.accepted && result.commandId
    ? launcherLifecycleSupervisor.bindCommand(intentLease, { commandId: result.commandId })
    : intentLease;
  if (lease === null || !launcherLifecycleSupervisor.isCurrent(lease)) {
    return supersededLifecycleResult(operation, result.commandId);
  }
  if (result.accepted && (operation === "start" || operation === "restart" || operation === "rebuild-and-start")) {
    const provider = windowProvider;
    if (provider !== null && result.commandId) {
      const readyWaitMs = operation === "rebuild-and-start"
        ? WORKBENCH_REBUILD_READY_WAIT_MS
        : WORKBENCH_START_READY_WAIT_MS;
      void openWorkbenchAfterLifecycleReady(paths, launcherBootstrap, provider, lease, readyWaitMs)
        .catch((error: unknown) => {
          if (!lease.signal.aborted) {
            console.warn(error instanceof Error ? error.message : String(error));
          }
        });
    }
  }
  if (
    result.accepted
    && desiredState === "closed"
    && result.commandId
    && launcherLifecycleSupervisor.isCurrent(lease)
    && !shouldDeferOrchestratedWindowClose(payload)
  ) {
    const provider = windowProvider;
    if (provider !== null) {
      void provider.approveWorkbenchCloseOnce().catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
    }
  }
  return {
    ...result,
    ...(forceAuthorization ? { requestId: forceAuthorization.requestId } : {})
  };
}

function normalizeSupervisedLifecycleOperation(operation: string): SupervisedLifecycleOperation {
  const normalized = operation.trim().toLowerCase();
  if (
    normalized === "start"
    || normalized === "stop"
    || normalized === "force-stop"
    || normalized === "restart"
    || normalized === "rebuild-and-start"
    || normalized === "shutdown"
    || normalized === "close"
  ) {
    return normalized;
  }
  throw new Error(`unsupported Launcher lifecycle operation: ${operation}`);
}

function desiredStateForLifecycleOperation(operation: SupervisedLifecycleOperation): LauncherDesiredState {
  return operation === "start" || operation === "restart" || operation === "rebuild-and-start"
    ? "open"
    : "closed";
}

function shouldDeferOrchestratedWindowClose(payload: LauncherIpcInvokePayload): boolean {
  const body = payload.init?.body;
  if (typeof body !== "object" || body === null) {
    return false;
  }
  const record = body as Record<string, unknown>;
  if (record.deferWindowClose !== true) {
    return false;
  }
  const closeId = String(record.closeId ?? "").trim();
  const transaction = closeId ? mainWorkbenchCloseStore.get(closeId) : null;
  if (transaction === null || transaction.phase !== "backend_closing") {
    return false;
  }
  return String(transaction.requestId ?? "") === String(record.requestId ?? "").trim();
}

function supersededLifecycleResult(operation: string, commandId = ""): OrchestratedLifecycleResult {
  return {
    schemaVersion: 1,
    accepted: false,
    operation,
    ...(commandId ? { commandId } : {}),
    code: "lifecycle_intent_superseded",
    message: "A newer Launcher lifecycle intent superseded this command."
  };
}

function isCurrentCheckoutInstance(instanceId: string): boolean {
  return instanceId === "main";
}

function rememberLiveWorkbenchUrl(url: string): string {
  const safe = url.trim();
  if (!safe) {
    return resolveOrchestratedWorkbenchUrl();
  }
  currentWorkbenchUrl = safe;
  if (launcherBootstrap !== null) {
    launcherBootstrap = { ...launcherBootstrap, workbenchUrl: safe };
  }
  return safe;
}

async function refreshLiveWorkbenchUrl(paths: DesktopPaths): Promise<string> {
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    return resolveOrchestratedWorkbenchUrl();
  }
  try {
    const resolved = await resolveWorkbenchUrlFromBridge({
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim()
    });
    return rememberLiveWorkbenchUrl(resolveWorkbenchUrl(desktopEnv, resolved));
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
    return resolveOrchestratedWorkbenchUrl();
  }
}

function resolveOrchestratedWorkbenchUrl(port?: number): string {
  if (typeof port === "number" && Number.isFinite(port) && port > 0) {
    return workbenchLoopbackUrl(port);
  }
  if (currentWorkbenchUrl.trim()) {
    try {
      return resolveWorkbenchUrl(desktopEnvironment(), currentWorkbenchUrl);
    } catch {
      // Fall through to bootstrap / default loopback.
    }
  }
  try {
    return resolveWorkbenchUrl(desktopEnvironment(), launcherBootstrap?.workbenchUrl);
  } catch {
    return workbenchLoopbackUrl();
  }
}

function closeOrchestratedWorkbenchWindow(instanceId: string): void {
  const provider = windowProvider;
  if (provider === null) {
    return;
  }
  const closed = isCurrentCheckoutInstance(instanceId)
    ? provider.approveWorkbenchCloseOnce()
    : provider.closeInstanceWorkbench(instanceId);
  void closed.catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
}

async function closeWindowIfSupersededByClosedIntent(instanceId: string): Promise<void> {
  if (launcherLifecycleSupervisor.snapshot(instanceId)?.desiredState !== "closed") {
    return;
  }
  const provider = windowProvider;
  if (provider === null) {
    return;
  }
  if (isCurrentCheckoutInstance(instanceId)) {
    await provider.approveWorkbenchCloseOnce();
    return;
  }
  await provider.closeInstanceWorkbench(instanceId);
}

async function openWorkbenchForCloseCanary(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider
): Promise<void> {
  electronStartupStage = "workbench_window_ready";
  markWorkbenchOpenRequested();
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("Workbench close canary requires a managed Python lifecycle bridge.");
  }
  const intentLease = launcherLifecycleSupervisor.beginIntent({
    instanceId: "main",
    operation: "start",
    desiredState: "open"
  });
  const mutation = await launcherLifecycleSupervisor.executeMutation({
    lease: intentLease,
    mutate: async () => await runWorkbenchLifecycle({
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        bootstrap.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
      operation: "start",
      signal: intentLease.signal
    }),
    reconcile: async () => {
      scheduleLauncherStatusCliRefresh();
    }
  });
  if (mutation.outcome === "failed") {
    throw mutation.error;
  }
  if (mutation.outcome === "uncertain") {
    throw new Error("Workbench close canary start outcome is uncertain; reconciliation started.");
  }
  if (mutation.outcome === "ignored" || mutation.outcome === "superseded") {
    return;
  }
  const startResult = mutation.value;
  if (startResult.accepted) {
    const lease = startResult.commandId
      ? launcherLifecycleSupervisor.bindCommand(intentLease, { commandId: startResult.commandId })
      : null;
    if (lease === null) {
      throw new Error("Workbench close canary start did not return a current command id.");
    }
    await openWorkbenchAfterLifecycleReady(
      paths,
      bootstrap,
      provider,
      lease,
      WORKBENCH_START_READY_WAIT_MS
    );
    return;
  }
  throw new Error(startResult.message || startResult.code || "Workbench close canary start was not accepted.");
}

async function openWorkbenchAfterLifecycleReady(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  provider: ElectronWindowProvider,
  lease: LauncherLifecycleLease,
  _timeoutMs: number
): Promise<void> {
  // I4b already waited for backend health before returning. Do not poll Python
  // runtime-manager result files: Electron main-line never writes them, so a
  // 90s wait used to block the workbench window after a successful start.
  if (!launcherLifecycleSupervisor.isCurrent(lease)) {
    return;
  }
  const url = await refreshLiveWorkbenchUrl(paths);
  if (!launcherLifecycleSupervisor.isCurrent(lease) || !launcherLifecycleSupervisor.claimReady(lease)) {
    return;
  }
  try {
    await openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, { workbenchUrl: url });
  } catch (error: unknown) {
    launcherLifecycleSupervisor.releaseReadyClaim(lease);
    throw error;
  }
  if (!launcherLifecycleSupervisor.isCurrent(lease)) {
    await closeWindowIfSupersededByClosedIntent(lease.instanceId);
    return;
  }
  if (!launcherLifecycleSupervisor.completeReady(lease)) {
    if (launcherLifecycleSupervisor.isCurrent(lease)) {
      launcherLifecycleSupervisor.releaseReadyClaim(lease);
      await provider.approveWorkbenchCloseOnce();
      throw new Error(`Launcher lifecycle READY completion failed for ${lease.instanceId}.`);
    }
    await closeWindowIfSupersededByClosedIntent(lease.instanceId);
  }
}

async function runIsolatedRegistryMutation(input: {
  operation: BranchInstanceOperation;
  instanceId: string;
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  signal?: AbortSignal;
}): Promise<OrchestratedBranchInstanceResult> {
  if (input.operation === "observe-error" || input.operation === "observe-ready") {
    throw new Error("isolated observe must use instanceRegistryStore, not the Python bridge");
  }
  const payload = launcherStateStore.projectBranchInstances();
  const target = resolveIsolatedClaimTarget(payload, input.instanceId);

  if (input.operation === "start" || input.operation === "restart") {
    if (input.operation === "start" && target?.alive) {
      return {
        schemaVersion: 1,
        accepted: true,
        operation: input.operation,
        instanceId: input.instanceId,
        port: target.preferredBackend,
        controlPort: target.preferredControl,
        message: "已打开该分支工作台窗口。"
      };
    }
    if (target) {
      const claimed = await claimIsolatedStart({
        instanceId: input.instanceId,
        branchInstances: payload,
        operation: input.operation,
        commandId: randomUUID()
      });
      if (!claimed.ok) {
        return {
          schemaVersion: 1,
          accepted: false,
          operation: input.operation,
          instanceId: input.instanceId,
          generation: claimed.generation,
          code: "instance_busy",
          message: "该分支实例正在执行生命周期操作。"
        };
      }
      const port = Number(claimed.entry.port || target.preferredBackend || 0);
      const controlPort = Number(claimed.entry.controlPort || target.preferredControl || 0);
      const dataHome = String(claimed.entry.dataHome || "").trim() || resolveDataHomeForProject(target.projectRoot);
      const spawned = spawnWorkbenchBackend({
        workspaceRoot: target.projectRoot,
        scriptRoot: target.projectRoot,
        pythonPath: input.pythonPath,
        port,
        controlPort,
        dataHome,
        configHome: resolveConfigHome(),
        allowDirty: true,
        allowNonMain: true
      });
      const spawnPid = Number(spawned.child.pid || 0);
      const generation = Number(claimed.entry.generation || 0);
      if (spawnPid > 0 && generation > 0) {
        const recorded = await recordSpawnPid(instancesRegistryPath(), {
          instanceId: input.instanceId,
          spawnPid,
          expectedGeneration: generation
        });
        if (!recorded.applied) {
          spawned.child.kill();
          return {
            schemaVersion: 1,
            accepted: false,
            operation: input.operation,
            instanceId: input.instanceId,
            generation,
            code: "spawn_pid_cas_miss",
            message: "spawn pid CAS missed"
          };
        }
      }
      try {
        await waitForBackendHealthy({
          port,
          signal: input.signal,
          childAlive: () => spawned.child.exitCode == null && spawned.child.killed !== true
        });
      } catch (error: unknown) {
        spawned.child.kill();
        throw error;
      }
      return {
        schemaVersion: 1,
        accepted: true,
        operation: input.operation,
        instanceId: input.instanceId,
        generation,
        commandId: String(claimed.entry.commandId || ""),
        port,
        controlPort: Number(claimed.entry.controlPort || 0),
        deadlineAt: String(claimed.entry.deadlineAt || "")
      };
    }
    return {
      schemaVersion: 1,
      accepted: false,
      operation: input.operation,
      instanceId: input.instanceId,
      code: "instance_not_found",
      message: `找不到分支实例：${input.instanceId}`
    };
  }

  if (input.operation === "stop" || input.operation === "force-stop") {
    const claimed = await claimIsolatedStop({
      instanceId: input.instanceId,
      branchInstances: payload
    });
    await retireRegisteredHandles({
      pids: [Number(claimed.entry.spawnPid || 0)],
      port: Number(claimed.entry.port || target?.preferredBackend || 0),
      signal: input.signal
    });
    return {
      schemaVersion: 1,
      accepted: true,
      operation: input.operation,
      instanceId: input.instanceId,
      generation: Number(claimed.entry.generation || 0)
    };
  }

  return {
    schemaVersion: 1,
    accepted: false,
    operation: input.operation,
    instanceId: input.instanceId,
    code: "unsupported_isolated_operation",
    message: `Unsupported isolated operation: ${input.operation}`
  };
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
  if (isCurrentCheckoutInstance(instanceId)) {
    const mainResult = await orchestrateLauncherLifecycle(operation, payload);
    return { ...mainResult, instanceId };
  }
  const forceAuthorization = await authorizeLauncherForceLifecycle({
    operation,
    instanceId,
    payload,
    operatorIntent: payload.path || operation
  });
  const supervisedOperation = normalizeSupervisedLifecycleOperation(operation);
  const desiredState = desiredStateForLifecycleOperation(supervisedOperation);
  const intentLease = launcherLifecycleSupervisor.beginIntent({
    instanceId,
    operation: supervisedOperation,
    desiredState
  });
  const paths = createDesktopPathsForApp();
  const mutation = await launcherLifecycleSupervisor.executeMutation({
    lease: intentLease,
    mutate: async () => await runIsolatedRegistryMutation({
      operation: operation as BranchInstanceOperation,
      instanceId,
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
      signal: intentLease.signal
    }),
    reconcile: async () => {
      scheduleLauncherStatusCliRefresh();
    }
  });
  if (mutation.outcome === "failed") {
    throw mutation.error;
  }
  if (mutation.outcome === "uncertain") {
    throw new Error(`Branch lifecycle ${operation} outcome is uncertain; reconciliation started.`);
  }
  if (mutation.outcome === "ignored") {
    return supersededBranchLifecycleResult(operation, instanceId);
  }
  const result = mutation.value;
  if (mutation.outcome === "superseded") {
    return supersededBranchLifecycleResult(operation, instanceId, result.commandId);
  }
  const lease = result.accepted && result.commandId
    ? launcherLifecycleSupervisor.bindCommand(intentLease, {
        commandId: result.commandId,
        generation: result.generation
      })
    : intentLease;
  if (lease === null || !launcherLifecycleSupervisor.isCurrent(lease)) {
    return supersededBranchLifecycleResult(operation, instanceId, result.commandId);
  }
  if (result.accepted && (operation === "start" || operation === "restart")) {
    if (result.port && result.port > 0 && result.commandId) {
      const url = workbenchLoopbackUrl(result.port);
      const provider = windowProvider;
      void superviseIsolatedInstanceStart({
        instanceId,
        url,
        lease,
        isCurrent: (candidate) => launcherLifecycleSupervisor.isCurrent(candidate),
        claimReady: (candidate) => launcherLifecycleSupervisor.claimReady(candidate),
        completeReady: (candidate) => launcherLifecycleSupervisor.completeReady(candidate),
        releaseReadyClaim: (candidate) => launcherLifecycleSupervisor.releaseReadyClaim(candidate),
        deadlineAt: result.deadlineAt,
        waitForHttp: (target, timeoutMs, signal) => waitForWorkbenchHttp({ url: target, timeoutMs, signal }),
        openWindow: async () => {
          if (provider === null) {
            throw new Error("window provider is unavailable");
          }
          await provider.openOrFocusInstanceWorkbench({ instanceId, url });
        },
        closeWindowIfSuperseded: async () => {
          await closeWindowIfSupersededByClosedIntent(instanceId);
        },
        closeWindowAfterReadyFailure: async () => {
          if (provider !== null) {
            await provider.closeInstanceWorkbench(instanceId);
          }
        },
        markReady: async (observedGeneration) => {
          await observeIsolatedReady({
            instanceId,
            expectedGeneration: observedGeneration
          });
        },
        markError: async (observedGeneration, message) => {
          await observeIsolatedError({
            instanceId,
            expectedGeneration: observedGeneration,
            message
          });
        },
        renewLease: async () => {
          await renewIsolatedOwnerLease({
            instanceId,
            ownerId: `pid:${process.pid}`,
            expectedGeneration: lease.generation
          });
        }
      }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
    }
  }
  if (
    result.accepted
    && desiredState === "closed"
    && result.commandId
    && launcherLifecycleSupervisor.isCurrent(lease)
  ) {
    closeOrchestratedWorkbenchWindow(instanceId);
  }
  return {
    ...result,
    ...(forceAuthorization ? { requestId: forceAuthorization.requestId } : {})
  };
}

function supersededBranchLifecycleResult(
  operation: string,
  instanceId: string,
  commandId = ""
): OrchestratedBranchInstanceResult {
  return {
    schemaVersion: 1,
    accepted: false,
    operation,
    instanceId,
    ...(commandId ? { commandId } : {}),
    code: "lifecycle_intent_superseded",
    message: "A newer Launcher lifecycle intent superseded this command."
  };
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
    failureLabel: "launcher api bridge",
    maxBytes: LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
    timeoutMs:
      path === "maintenance/reset/apply"
        ? PYTHON_JSON_BRIDGE_MAINTENANCE_TIMEOUT_MS
        : method === "GET"
          ? PYTHON_JSON_BRIDGE_QUERY_TIMEOUT_MS
          : PYTHON_JSON_BRIDGE_COMMAND_TIMEOUT_MS,
    killPolicy: "child",
    mutation: method !== "GET"
  });
  const parsed = parsePythonJsonBridgePayload<{ ok?: boolean; payload?: unknown; message?: string }>(
    raw,
    "launcher api bridge"
  );
  if (!parsed || typeof parsed.ok !== "boolean") {
    throw invalidPythonJsonBridgePayload("launcher api bridge", "returned an invalid result shape");
  }
  if (parsed.ok !== true) {
    throw new Error(parsed.message || "launcher api bridge failed");
  }
  return parsed.payload;
}

function scheduleLauncherStatusCliRefresh(): void {
  if (launcherBootstrap === null) {
    return;
  }
  void launcherStateStore.refresh("launcher_status_refresh");
}

function launcherStateStatSignature(path: string): string {
  try {
    const stat = statSync(path);
    return `${stat.mtimeMs}:${stat.size}`;
  } catch {
    return "missing";
  }
}

function scheduleLauncherStateFileHint(): void {
  if (launcherStateHintTimer !== null) {
    clearTimeout(launcherStateHintTimer);
  }
  launcherStateHintTimer = setTimeout(() => {
    launcherStateHintTimer = null;
    void launcherStateStore.refresh("file_change");
  }, 200);
}

function startLauncherStateFileHints(paths: DesktopPaths): void {
  stopLauncherStateFileHints();
  const localAppData = String(desktopEnvironment().LOCALAPPDATA || "").trim();
  const runtimeDir = resolve(paths.workspaceRoot, ".runtime", "launcher");
  const statTargets = [
    resolve(runtimeDir, "state.json"),
    resolve(runtimeDir, "ports.json"),
    resolve(paths.workspaceRoot, ".git"),
    ...(localAppData ? [resolve(localAppData, "Vibelution", "instances.json")] : [])
  ];
  const watchTargets = [
    runtimeDir,
    resolve(paths.workspaceRoot, ".git"),
    ...(localAppData ? [resolve(localAppData, "Vibelution")] : [])
  ];
  for (const target of statTargets) {
    launcherStateStatSignatures.set(target, launcherStateStatSignature(target));
  }
  for (const target of watchTargets) {
    try {
      const watcher = watch(target, { persistent: false }, () => scheduleLauncherStateFileHint());
      watcher.on("error", () => undefined);
      launcherStateWatchers.push(watcher);
    } catch {
      // Missing runtime paths are covered by the stat-only safety check below.
    }
  }
  launcherStateStatTimer = setInterval(() => {
    let changed = false;
    for (const target of statTargets) {
      const next = launcherStateStatSignature(target);
      if (launcherStateStatSignatures.get(target) !== next) {
        launcherStateStatSignatures.set(target, next);
        changed = true;
      }
    }
    if (changed) {
      scheduleLauncherStateFileHint();
    }
  }, 30_000);
  launcherStateStatTimer.unref?.();
}

function stopLauncherStateFileHints(): void {
  if (launcherStateHintTimer !== null) {
    clearTimeout(launcherStateHintTimer);
    launcherStateHintTimer = null;
  }
  if (launcherStateStatTimer !== null) {
    clearInterval(launcherStateStatTimer);
    launcherStateStatTimer = null;
  }
  reconcileDeadlineScheduler.clear();
  for (const watcher of launcherStateWatchers) {
    watcher.close();
  }
  launcherStateWatchers = [];
  launcherStateStatSignatures.clear();
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
      try {
        const context = await resolveDesktopActionLoopContext(launcherBootstrap);
        return {
          launcherOrigin: context.launcherOrigin,
          controlToken: context.controlToken
        };
      } catch {
        return null;
      }
    },
    resolveWindowTruth: currentLauncherWindowTruth,
    orchestrateLifecycle: async (operation, payload) => {
      launcherStateStore.markReconciliation(`lifecycle:${operation}`);
      try {
        return await orchestrateLauncherLifecycle(operation, payload);
      } finally {
        scheduleLauncherStatusCliRefresh();
      }
    },
    orchestrateBranchInstance: async (operation, payload) => {
      launcherStateStore.markReconciliation(`branch_lifecycle:${operation}`);
      try {
        return await orchestrateBranchInstanceLifecycle(operation, payload);
      } finally {
        scheduleLauncherStatusCliRefresh();
      }
    },
    orchestrateLauncherApi: async (path, payload) => {
      const result = await orchestrateLauncherApi(path, payload);
      if (String(payload.init?.method ?? "GET").toUpperCase() !== "GET") {
        scheduleLauncherStatusCliRefresh();
      }
      return result;
    },
    resolveLocalStatus: () => launcherStateStore.projectStatus(),
    resolveLocalBranchInstances: () => launcherStateStore.projectBranchInstances()
  });
  return launcherIpcHost;
}

ipcMain.handle(IPC_CHANNELS.launcherInvoke, async (event, payload: LauncherIpcInvokePayload) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return await resolveLauncherIpcHost().invoke(payload);
});

ipcMain.handle(IPC_CHANNELS.getLauncherState, (event) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return launcherStateStore.snapshot();
});

ipcMain.handle(IPC_CHANNELS.refreshLauncherState, async (event) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return await launcherStateStore.refresh("user_recheck");
});

async function startOrFocusWorkbenchFromProductEntryOnShell(): Promise<void> {
  const provider = windowProvider;
  if (provider === null) {
    pendingOpenWorkbenchRequest = true;
    return;
  }
  pendingOpenWorkbenchRequest = false;
  markWorkbenchOpenRequested();
  const paths = createDesktopPathsForApp();
  const url = launcherBootstrap !== null
    ? await refreshLiveWorkbenchUrl(paths)
    : resolveOrchestratedWorkbenchUrl();
  try {
    await startOrFocusWorkbenchFromProductEntry({
      url,
      waitForHttp: (opts) => waitForWorkbenchHttp(opts),
      openOrFocus: (target) => provider.openOrFocusWorkbench(target),
      startLifecycle: () => orchestrateLauncherLifecycle("start", { schemaVersion: 1, path: "open" })
    });
  } finally {
    scheduleLauncherStatusCliRefresh();
  }
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
  await startOrFocusWorkbenchFromProductEntryOnShell();
}

async function applyPendingProjectSlot(projectRoot: string, lifecycleCommand = ""): Promise<void> {
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
    await launcherStateStore.refresh("project_slot");
    let items = parseBranchInstanceRecords(launcherStateStore.projectBranchInstances());
    const needsLookup = () => {
      try {
        planProjectSlot({ items, projectRoot: wanted, lifecycleCommand: "status" });
        return false;
      } catch {
        return true;
      }
    };
    if (needsLookup()) {
      items = parseBranchInstanceRecords(
        await orchestrateLauncherApi("branch-instances", {
          schemaVersion: 1,
          path: "branch-instances",
          init: { method: "GET" }
        })
      );
    }
    const plan = planProjectSlot({
      items,
      projectRoot: wanted,
      lifecycleCommand
    });
    if (plan.operation) {
      if (plan.isMain) {
        await orchestrateLauncherLifecycle(plan.operation, {
          schemaVersion: 1,
          path: "project-slot"
        });
      } else {
        await orchestrateBranchInstanceLifecycle(plan.operation, {
          schemaVersion: 1,
          path: `branch-instances/${plan.operation}`,
          init: {
            method: "POST",
            body: { instanceId: plan.instanceId }
          }
        });
      }
    }
    if (plan.operation === "stop" || plan.operation === "force-stop") {
      return;
    }
    let url = plan.url;
    try {
      await launcherStateStore.refresh("project_slot");
      url = planProjectSlot({
        items: parseBranchInstanceRecords(launcherStateStore.projectBranchInstances()),
        projectRoot: wanted,
        lifecycleCommand: "status"
      }).url || url;
    } catch {
      // Keep the planned URL when the refreshed list is still settling.
    }
    if (!url) {
      throw new Error(`工作区已匹配但没有可打开的地址：${plan.instanceId}`);
    }
    currentWorkbenchUrl = url;
    markWorkbenchOpenRequested();
    await provider.openOrFocusWorkbench(url);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `应用工作区失败：${detail.slice(0, 300)}`, "warning");
  }
}

if (runPrimaryWhenReady) {
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
    await reapManagedRuntimeOnDesktopStart({
      stopManagedRuntime,
      stopLeftoverPythonLauncher: stopOwnedPythonLauncherService,
      recordEvent: async (event) => {
        await recordElectronSupervisorEvent(launcherBootstrap, event);
      }
    });
    if (desktopCliArgs.smoke) {
      await runSmokeAndQuit(paths);
      return;
    }
    if (await refreshPackagedDesktopShellIfStale(thenLifecycleFromDesktopCli(desktopCliArgs))) {
      return;
    }
    const deepLinkRegistration = registerPackagedDeepLinks(paths);
    launcherBootstrap = await bootstrapMainOwnedLauncher(paths);
    electronStartupStage = "tray_ready";
    const trayStartedAtMs = performance.now();
    windowProvider = createWindowProvider(paths, launcherBootstrap);
    updateLauncherWindowTruth();
    startLauncherStateFileHints(paths);
    scheduleLauncherStatusCliRefresh();
    desktopTray = createDesktopTray(paths, {
      openLauncher: () => {
        void windowProvider?.openLauncher().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      },
      listInstances: async () => {
        return classifyTrayBranchInstances(launcherStateStore.projectBranchInstances());
      },
      getFreshness: async () => {
        const raw = launcherStateStore.projectFreshness();
        const freshness = typeof raw === "object" && raw !== null ? raw as Record<string, unknown> : {};
        return {
          current: freshness.current === true ? true : freshness.current === false ? false : null,
          label: typeof freshness.label === "string" && freshness.label.trim()
            ? freshness.label.trim()
            : "Launcher 代码版本：未知"
        };
      },
      restartLauncher: () => {
        void runTrayRestartLauncher();
      },
      startInstance: (instanceId, label) => {
        void runTrayBranchInstance("start", instanceId, `启动 ${label}`);
      },
      stopInstance: (instanceId, label) => {
        void runTrayBranchInstance("stop", instanceId, `停止 ${label}`);
      },
      stopAll: () => {
        void runTrayStopAll();
      }
    });
    startPeriodicShellFreshnessWatch();
    void maybeRestoreTrayRestartAllPending();
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
      message: "Electron main is the Launcher control plane; leftover Python launcher is not attached.",
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
    const firstLifecycle = String(desktopCliArgs.lifecycleCommand || "").trim().toLowerCase();
    const deferWorkbenchOpen = shouldDeferWorkbenchOpenUntilLifecycleStart(firstLifecycle);
    if (pendingOpenWorkbenchRequest && !desktopCliArgs.workbenchCloseCanary && !deferWorkbenchOpen) {
      electronStartupStage = "workbench_window_ready";
      await startOrFocusWorkbenchFromProductEntryOnShell();
    } else if (!desktopCliArgs.workbenchCloseCanary && !desktopCliArgs.projectRoot) {
      await windowProvider.openLauncher();
    }
    if (deferWorkbenchOpen) {
      pendingOpenWorkbenchRequest = false;
    }
    if (desktopCliArgs.workbenchCloseCanary) {
      if (launcherBootstrap === null) {
        throw new Error("Launcher bootstrap is unavailable for workbench close canary.");
      }
      await openWorkbenchForCloseCanary(paths, launcherBootstrap, windowProvider);
      return;
    }
    if (pendingProjectRoot) {
      await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle);
    } else if (firstLifecycle && firstLifecycle !== "status" && windowProvider !== null) {
      if (firstLifecycle === "open") {
        pendingOpenWorkbenchRequest = false;
        markWorkbenchOpenRequested();
        void startOrFocusWorkbenchFromProductEntryOnShell().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      } else {
        void handleSecondInstanceLifecycleCommand(firstLifecycle).catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      }
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
}

app.on("second-instance", (_event, argv) => {
  const secondCli = parseDesktopCliArgs(argv);
  const intent = resolveSecondInstanceIntent({
    deepLinkUrl: findVibelutionDeepLinkArg(argv) ?? "",
    projectRoot: secondCli.projectRoot,
    openWorkbench: secondCli.openWorkbench,
    lifecycleCommand: secondCli.lifecycleCommand
  });
  if (intent.action === "handle_deep_link") {
    void handlePublicDeepLinkUrl(intent.rawUrl, "second_instance");
    return;
  }
  if (intent.action === "apply_project") {
    void applyPendingProjectSlot(intent.projectRoot, intent.lifecycleCommand);
    return;
  }
  if (intent.action === "lifecycle") {
    void handleSecondInstanceLifecycleCommand(intent.command).catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    });
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
    stopLauncherStateFileHints();
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

app.on("will-quit", () => {
  stopLauncherStateFileHints();
});
