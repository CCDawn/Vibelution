import { BrowserWindow, Notification, app, dialog, ipcMain, nativeImage, nativeTheme, protocol, screen, shell, type IpcMainEvent, type IpcMainInvokeEvent } from "electron";
import { randomUUID } from "node:crypto";
import { requestRendererWindowClose } from "./windows/rendererWindowClose.js";
import { configureWindowsNotificationIdentity } from "./notifications/windowsNotificationIdentity.js";
import { NativeNotificationLifetime } from "./notifications/nativeNotificationLifetime.js";
import { handleHumanAttentionCapabilityIpc, handleHumanAttentionIpc } from "./notifications/humanAttentionIpc.js";
import { LegacyReminderSourceFence } from "./notifications/legacyReminderSourceFence.js";
import { createLegacyReminderSourceResolver } from "./notifications/resolveLegacyReminderSource.js";
import { mkdirSync, statSync, watch, writeFileSync, type FSWatcher } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { deflateSync } from "node:zlib";
import {
  createSingleInstanceEnvelope,
  pinSharedDesktopShellUserData,
  resolveSingleInstanceCliIntent,
  resolveSingleInstanceProvenance,
  resolveSecondInstanceIntent,
  shouldRunDesktopWhenReadyHandlers,
  singleInstanceDecision
} from "./appLock.js";
import {
  applyDesktopCliToEnvironment,
  parseDesktopCliArgs,
  parseDesktopLifecycleLaunchMetadata
} from "./cli/desktopCli.js";
import { IPC_CHANNELS } from "./ipc.js";
import { AssistantHost } from "./assistant/assistantHost.js";
import { InitialMigrationResults } from "./assistant/initialMigrationResults.js";
import { verifyInitialMigrationResult } from "./assistant/initialMigrationJob.js";
import { recoverInitialMigrations } from "./assistant/initialMigrationStartup.js";
import { unknownAffairsSyncResult, unknownEpisodicSyncResult } from "./assistant/mainControlTransport.js";
import { startAssistantReminderPump } from "./assistant/reminderPump.js";
import { AssistantProjectRegistryConnection } from "./assistant/projectRegistryConnection.js";
import { createAssistantAppearanceMainControl } from "./assistant/appearanceMainControl.js";
import { createAssistantProjectMainControl } from "./assistant/projectMainControl.js";
import { AssistantWindow } from "./assistant/assistantWindow.js";
import { resolveAssistantResources } from "./assistant/assistantResources.js";
import { createAssistantTray } from "./assistant/assistantTray.js";
import { createAssistantLauncherEntry } from "./assistant/launcherEntry.js";
import { configureLocalDebugging, identifyDebugWindow, publishLocalDebugging } from "./debugging/localDebugging.js";
import { captureElectronOwnerIdentity } from "./tray/desktopShellOwner.js";
import { startNativeLauncherStartTransport } from "./process/nativeLauncherStart.js";
import {
  DESKTOP_LAUNCH_PROFILE_FILE,
  applyDesktopLaunchSettingsToEnvironment,
  resolveDesktopLaunchSettings,
  resolveDeferredProjectLaunchSettings,
  type DesktopLaunchSettings
} from "./launch/desktopLaunchSettings.js";
import { RuntimeSceneBridge, type RuntimeSceneElectronEvent } from "./lifecycle/runtimeSceneBridge.js";
import {
  startLauncherActiveReleaseWatcher,
  type LauncherActiveReleaseWatcherHandle
} from "./process/launcherActiveReleaseWatcher.js";
import {
  LauncherLifecycleSupervisor,
  type LauncherDesiredState,
  type LauncherLifecycleLease,
  type LauncherLifecycleOperation as SupervisedLifecycleOperation
} from "./lifecycle/launcherLifecycleSupervisor.js";
import {
  isForceLifecycleAuthorizationDenied,
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
import { fulfillDeferredRestartIntentOnce } from "./lifecycle/deferredRestartIntents.js";
import { waitForWorkbenchBackendSettledForWindowClose } from "./lifecycle/workbenchBackendCloseReadiness.js";
import type { WorkbenchCloseTiming } from "./process/fastWorkbenchClose.js";
import { getBackgroundWorkbenchRetirement, hasBackgroundWorkbenchRetirement } from "./process/backgroundWorkbenchRetirement.js";
import { runWithFrontendBuildGate } from "./lifecycle/frontendBuildState.js";
import { beginLaunchRequestReceipt } from "./lifecycle/launchRequestReceipt.js";
import { readRuntimeManagerLauncherStatusSummary } from "./lifecycle/runtimeManagerStatusSnapshot.js";
import {
  createConversationNotificationService,
  type ConversationNotificationService,
  type DesktopConversationCompletionNotification,
  type DesktopConversationNotificationResult
} from "./notifications/conversationNotifications.js";
import {
  createHumanAttentionNotificationService,
  type HumanAttentionNotificationService
} from "./notifications/humanAttentionNotifications.js";
import { createDesktopPaths, resolveDesktopBundleRoot, resolveDesktopEntryCatalogPath, type DesktopPaths } from "./paths.js";
import { fetchLauncherControlToken, runDesktopActionOnce } from "./protocol/desktopActionClient.js";
import { BackendControlTokenOwner } from "./protocol/backendControlToken.js";
import { PROJECT_SLOT_LIFECYCLE_COMMANDS, planProjectSlot, projectSlotWindowAction } from "./protocol/applyProjectSlot.js";
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
import { LauncherStateStore, unwrapSource, type LauncherWindowTruth } from "./state/launcherStateStore.js";
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
  ensureFrontendRelease,
  launcherStatePath,
  mainLineBackendIsReachable,
  mainLineBackendIsReusable,
  readLauncherStateFile,
  spawnWorkbenchBackend
} from "./process/workbenchBackend.js";
import { captureTrackedWorkbenchJobRetirement } from "./process/workbenchJob.js";
import { captureFrontendBuildRetirement } from "./process/ownedFrontendBuildBridge.js";
import { waitForPortRelease } from "./process/workbenchBackendRetire.js";
import { waitForBackendHealthy } from "./process/workbenchBackendHealth.js";
import {
  inspectWorkbenchServingVersion,
  verifyRestartedServingVersion,
  type ServingProcessIdentity
} from "./process/servingVersion.js";
import { recordAdmissionOutcome } from "./lifecycle/instanceAdmissionStore.js";
import { normalizeInstanceKey, resolveActiveCanonicalRuntimeHome, resolveConfigHome, resolveDataHomeForProject, resolveRuntimeManagerDir } from "./lifecycle/projectStoragePaths.js";
import {
  claimStopIfGeneration,
  instancesRegistryPath,
  readRegistry,
  recordSpawnPid,
  upsert
} from "./lifecycle/instanceRegistryStore.js";
import { reconcileOrphanedInstanceRegistry } from "./lifecycle/instanceRegistryRecovery.js";
import { reconcileRegistryWithObservation } from "./lifecycle/instanceRegistryReconciler.js";
import { knownPidIsAlive } from "./lifecycle/mainLine/observation.js";
import {
  superviseIsolatedInstanceStart
} from "./process/isolatedInstanceSupervisor.js";
import {
  type BranchInstanceOperation,
  claimIsolatedStop,
  inspectIsolatedStartReuse,
  observeIsolatedError,
  observeIsolatedReady,
  prepareIsolatedStart,
  retireClaimedIsolatedRuntime,
  renewIsolatedOwnerLease,
  resolveIsolatedClaimTarget
} from "./lifecycle/isolatedInstanceRegistryHost.js";
import {
  invalidPythonJsonBridgePayload,
  LAUNCHER_API_JSON_BRIDGE_MAX_BYTES,
  launcherApiBridgeTimeoutMs,
  parsePythonJsonBridgePayload,
  runPythonJsonBridge,
  capturePythonProcessIdentity,
  createPythonOwnedProcessTreeTerminator
} from "./process/pythonJsonBridge.js";
import { resolveWorkbenchUrlFromBridge } from "./process/resolveWorkbenchBridge.js";
import {
  decideLauncherShellRestart,
  decidePackagedDesktopShellRefresh,
  decidePeriodicDesktopShellRefresh,
  shouldProbePeriodicDesktopShell,
  inspectDesktopShell,
  inspectDesktopShellLaunchReadiness,
  inspectUnpackagedShell,
  scheduleDesktopShellRefresh,
  ensureLatestLauncher,
  shouldDeferWorkbenchOpenUntilLifecycleStart,
  shouldInspectDesktopShellBeforeLifecycle,
  shouldRefreshBeforeLifecycle,
  thenLifecycleFromDesktopCli,
  type DesktopShellStatus,
  type DesktopShellLaunchReadiness
} from "./process/desktopShellFreshness.js";
import {
  completeBootstrapWithoutWaitingForTelemetry,
  drainTelemetryWithDeadline,
  scheduleTelemetryWithoutWaiting,
  type LauncherBootstrapResult
} from "./process/launcherBootstrap.js";
import { listActiveWorkRuns } from "./process/activeWorkGuard.js";
import { executeLauncherUpdate, projectLauncherUpdateFreshness, retainKnownDesktopShell } from "./process/launcherUpdate.js";
import { assertTrustedIpcSender } from "./security/ipcSenderValidation.js";
import { isExternalOpenableUrl, normalizeAbsoluteOpenPath } from "./security/externalOpenPolicy.js";
import { isLiveWorkbenchWindowUrl } from "./security/urlPolicy.js";
import { createDesktopShellExitDeadline, executeApprovedDesktopShellShutdown, reapManagedRuntimeOnDesktopStart, DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS, withDesktopShellExitTimeout, type DesktopShellExitDeadline } from "./shutdown/desktopShellExit.js";
import {
  decideShutdown,
  executeShutdownAuthorizationBoundary,
  fetchLauncherActiveWorkStatus,
  activeWorkStatusFromLauncherStatus,
  isActiveWorkProbeAuthFailure,
  resolveQuitActiveWorkStatus,
  type ActiveWorkProbeState,
  type ActiveWorkStatus,
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
  captureShutdownInstanceIds,
  registryEntriesToShutdownInstanceSnapshots,
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
import { createPetWindow, isDesktopPetWindowUrl } from "./windows/petWindow.js";
import { createPetSettingsControl, petSettingsOrigin } from "./windows/petSettingsControl.js";
import { desktopPetWindowExpandedBounds } from "./windows/petWindowBounds.js";
import {
  beginDesktopPetWindowDrag,
  desktopPetWindowBoundsAt,
  isDesktopPetDragPoint,
  type DesktopPetWindowDrag,
} from "./windows/petWindowDrag.js";
import {
    resolveLauncherWindowUrl,
  resolveWorkbenchUrl
} from "./windows/windowUrlResolver.js";
import { startOrFocusWorkbenchFromProductEntry } from "./windows/productEntryWorkbench.js";
import { waitForWorkbenchHttp, workbenchLoopbackUrl } from "./windows/workbenchHttpReady.js";
import { ensureWorkbenchBackendReady } from "./windows/workbenchOpenBackendGate.js";
import {
  startWorkbenchBackendWatchdog,
  type WorkbenchBackendWatchdogHandle
} from "./windows/workbenchBackendWatchdog.js";
import { installBrokenPipeGuards } from "./runtime/brokenPipeGuard.js";
import {
  MainWorkbenchCloseTransactionStore,
  isWorkbenchStartBlockedByClose,
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
const QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS = DESKTOP_SHELL_EXIT_STEP_TIMEOUT_MS;
const DESKTOP_QUIT_TOTAL_BUDGET_MS = 30_000;
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
// Last confirmed context for local close/stop snapshots; new writes use the
// backend-bound owner instead of trusting this value as an auth cache.
let desktopActionContext: DesktopActionLoopContext | null = null;
let backendControlTokenOwner: BackendControlTokenOwner | null = null;
let runtimeSceneBridge: RuntimeSceneBridge | null = null;
let runtimeSceneBridgeOpening: Promise<RuntimeSceneBridge> | null = null;
let desktopTray: ReturnType<typeof createDesktopTray> | null = null;
let currentWorkbenchUrl = "";
let desktopSessionRegistered = false;
let desktopSessionRevision = 0;
let desktopControlRecoveryPromise: Promise<void> | null = null;
let shutdownApproved = false;
let launcherIpcHost: ReturnType<typeof createLauncherIpcHost> | null = null;
let resolveLauncherControlPlaneReady: (() => void) | null = null;
const launcherControlPlaneReady = new Promise<void>((resolve) => {
  resolveLauncherControlPlaneReady = resolve;
});
let launcherStateWatchers: FSWatcher[] = [];
let launcherActiveReleaseWatcher: LauncherActiveReleaseWatcherHandle | null = null;
let launcherStateHintTimer: ReturnType<typeof setTimeout> | null = null;
let launcherStateStatTimer: ReturnType<typeof setInterval> | null = null;
let deferredRestartFulfillmentTimer: ReturnType<typeof setInterval> | null = null;
let deferredRestartFulfillmentInFlight = false;
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
    // Successful observation is the trigger for registry SSOT repair: adopt
    // live backends onto terminal/missing rows, settle rows whose registered
    // identity died, and sweep dead keys after their grace.
    scheduleRegistryReconciliation(state.branchInstances);
    // Only a successful native inventory observation may change assistant
    // permissions. Never derive them from instances.json or display parsing.
    // Applying permissions may wait for assistant startup/ACK. Launcher status
    // observation remains independent and does not advertise apply success.
    const assistantInventory = unwrapSource(state.branchInstances);
    // This observer consumes native _capture envelopes, before store projection.
    // Failed or legacy/unknown sources carry no permission-changing authority.
    if (assistantInventory.ok && !("legacy" in assistantInventory)) {
      void launcherAssistantProjects?.reconcile(assistantInventory.value).catch(() => console.warn("ASSISTANT_REGISTRY_UPDATE_FAILED"));
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
const WORKBENCH_CLOSE_BACKEND_WAIT_MS = 1_800;
const WORKBENCH_CLOSE_FORCE_AFTER_MS = 1_200;
const WORKBENCH_CLOSE_TOTAL_WAIT_MS = 2_000;
const WORKBENCH_START_READY_WAIT_MS = 90_000;
const WORKBENCH_REBUILD_READY_WAIT_MS = 300_000;
const desktopLifecycleCoordinator = new DesktopLifecycleCoordinator();
const desktopSessionMutations = new DesktopSessionMutationQueue();
const desktopSessionMirror = new DesktopSessionMirrorQueue((error: unknown) => {
  console.warn(error instanceof Error ? error.message : String(error));
});
let workbenchNotificationServices = new WeakMap<object, {
  origin: string;
  service: ConversationNotificationService;
  target: NonNullable<ReturnType<ElectronWindowProvider["notificationTargetForSender"]>>;
}>();
let humanAttentionNotificationService: HumanAttentionNotificationService | null = null;
const nativeNotificationLifetime = new NativeNotificationLifetime();
const desktopLaunchArgv = process.argv.slice(1);
const desktopCliArgs = (() => {
  try { return parseDesktopCliArgs(desktopLaunchArgv); }
  catch {
    console.warn("ASSISTANT_MODE_CONFLICT");
    app.exit(1);
    throw new Error("ASSISTANT_MODE_CONFLICT");
  }
})();
const desktopLifecycleLaunchMetadata = parseDesktopLifecycleLaunchMetadata(desktopLaunchArgv, process.env);
const singleInstanceEnvelope = createSingleInstanceEnvelope({
  assistant: desktopCliArgs.assistant,
  launchRequestId: desktopCliArgs.launchRequestId,
  workspaceRoot: desktopCliArgs.workspaceRoot,
  projectRoot: desktopCliArgs.projectRoot,
  openWorkbench: desktopCliArgs.openWorkbench,
  hiddenPresentation: desktopCliArgs.hiddenPresentation,
  lifecycleCommand: desktopLifecycleLaunchMetadata.command,
  lifecycleSource: desktopLifecycleLaunchMetadata.source,
  lifecycleReason: desktopLifecycleLaunchMetadata.reason,
  lifecycleStopManager: desktopLifecycleLaunchMetadata.stopManager,
  explicitlyForwarded: desktopLifecycleLaunchMetadata.explicitlyForwarded
});
const desktopLifecycleProvenance = resolveSingleInstanceProvenance(singleInstanceEnvelope);
let pendingOpenWorkbenchRequest = desktopCliArgs.openWorkbench;
let pendingProjectRoot = desktopCliArgs.projectRoot;
let cachedDesktopLaunchSettings: DesktopLaunchSettings | null = null;
let projectControlPlaneLaunchSettings: DesktopLaunchSettings | null = null;
let projectControlPlaneStartup: Promise<boolean> | null = null;
// Deferred management attaches observation and explicit controls, never cold-start recovery.
let projectControlPlaneAutomaticLifecycle = true;
let projectControlPlaneRecoveryNotBefore: number | undefined;
let projectControlPlaneObserversStarted = false;
let pendingWorkbenchCloseAck: PendingWorkbenchCloseAck | null = null;
let workbenchFailedCloseHandling = false;
let workbenchCloseGeneration = 0;
const workbenchOpenControllers = new Set<AbortController>();
let workbenchCloseBackendStopInFlight: Promise<void> | null = null;
let mainRuntimeShutdownInFlight: Promise<void> | null = null;
let electronStartupStage = "electron_process_ready";
let electronStartupSummaryRecorded = false;
let workbenchOpenRequestedAtMs: number | null = null;
let trayRestartAllInFlight = false;
let trayQuitAllInFlight = false;
let trayRestartLauncherInFlight = false;
let shellRefreshInFlight = false;
let lastKnownDesktopShell: DesktopShellStatus | undefined;
let periodicShellFreshnessTimer: ReturnType<typeof setInterval> | null = null;
let periodicAdvisoryStaleNotified = false;
let workbenchBackendWatchdog: WorkbenchBackendWatchdogHandle | null = null;

type DesktopActionLoopContext = {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
};

type PendingWorkbenchCloseAck = {
  closeId: string;
  desktopSessionId: string;
  requestedAtMs: number;
  projectionEpoch?: number;
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
const lockDecision = singleInstanceDecision(app.requestSingleInstanceLock(singleInstanceEnvelope));
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
const localDebuggingEnabled = configureLocalDebugging(app, desktopLaunchArgv,
  lockDecision.action === "continue_as_primary" && !desktopCliArgs.smoke && !desktopCliArgs.workbenchCloseCanary);
if (lockDecision.action === "continue_as_primary") configureWindowsNotificationIdentity(app);

let launcherAssistantHost: AssistantHost | null = null;
let launcherAssistantWindow: AssistantWindow | null = null;
let launcherAssistantExitReady = false;
let launcherAssistantStarting: Promise<void> | null = null;
let launcherAssistantStopping: Promise<void> | null = null;
const launcherAssistantStartupAbort = new AbortController();
let launcherAssistantProjects: AssistantProjectRegistryConnection | null = null;
let legacyReminderAdmission: {
  fence: LegacyReminderSourceFence;
  resolveSource: ReturnType<typeof createLegacyReminderSourceResolver>;
} | null = null;
let stopLauncherAssistantReminders: (() => Promise<void>) | null = null;
let assistantOnly = desktopCliArgs.assistant === true;
let pendingAssistantOpen: { show: boolean } | null = null;
let showAssistantStartupWait: (() => void) | null = null;
let dismissAssistantStartupWait: (() => void) | null = null;
let assistantMigrationPending = false;

async function requestOpenAssistantFromSecondInstance(hiddenPresentation: boolean): Promise<void> {
  if (shutdownApproved) throw new Error("ASSISTANT_NOT_READY");
  const show = !hiddenPresentation;
  if (launcherAssistantWindow) {
    await launcherAssistantWindow.open({ show });
    return;
  }
  // Ready may precede resource verification/window creation. Only remember
  // presentation; this request never creates or restarts a native host.
  pendingAssistantOpen = { show: pendingAssistantOpen?.show === true || show };
  if (show) showAssistantStartupWait?.();
}

let assistantLauncherEntry: ReturnType<typeof createAssistantLauncherEntry> | null = null;

function requestOpenLauncherFromAssistant(): Promise<{ opened: boolean }> {
  assistantLauncherEntry ??= createAssistantLauncherEntry({
    isQuitting: () => shutdownApproved,
    openExisting: async () => {
      if (!windowProvider || !launcherBootstrap) return false;
      await windowProvider.openLauncher();
      return true;
    },
    chooseProject: async () => {
      const selection = await dialog.showOpenDialog({ title: "选择要管理的 Vibelution 项目", properties: ["openDirectory"] });
      if (selection.canceled || selection.filePaths.length !== 1) return null;
      const root = selection.filePaths[0];
      // A fresh human selection supplies context, never a renderer/model path
      // or an automatic migration of the old registry's grants.
      try {
        if (!statSync(root).isDirectory() || !statSync(join(root, "core", "launcher")).isDirectory()
          || !statSync(join(root, "web", "package.json")).isFile()) throw new Error();
      } catch { throw new Error("ASSISTANT_LAUNCHER_UNAVAILABLE"); }
      return root;
    },
    connect: root => ensureProjectControlPlane(root, true),
    openConnected: async () => {
      if (!windowProvider) throw new Error("ASSISTANT_LAUNCHER_UNAVAILABLE");
      await windowProvider.openLauncher();
      startProjectControlPlaneObservers();
    },
  });
  return assistantLauncherEntry();
}

function startLauncherAssistant(paths: DesktopPaths): Promise<void> {
  if (launcherAssistantStarting) return launcherAssistantStarting;
  launcherAssistantStarting = (async () => {
    const projectConnection = new AssistantProjectRegistryConnection(join(paths.userDataRoot, "assistant", "projects.json"));
    launcherAssistantProjects = projectConnection;
    const initialMigrationStates = new Map<string, "queued" | "completed" | "partial" | "unknown">();
    let initialMigrationResults: InitialMigrationResults | null = null;
    let initialMigrationRecoveryUncertain = false;
    try {
      const directory = join(paths.userDataRoot, "assistant", "legacy-reminder-admission");
      mkdirSync(directory, { recursive: true });
      legacyReminderAdmission = { fence: new LegacyReminderSourceFence(directory),
        resolveSource: createLegacyReminderSourceResolver({ windowProvider: () => windowProvider,
          projectConnection: () => launcherAssistantProjects, readInstances: () => readRegistry(instancesRegistryPath()) }) };
    } catch {
      // The replacement consumer stays disabled when admission state cannot be opened.
      legacyReminderAdmission = null;
      console.warn("LEGACY_REMINDER_ADMISSION_UNAVAILABLE");
    }
    const projectMainControl = createAssistantProjectMainControl({
      directory: join(paths.userDataRoot, "assistant", "lifecycle-requests"), registry: projectConnection,
      operatorConfigPath: desktopLaunchSettings().configPath,
      launch: { env: process.env, cliArgs: desktopCliArgs, resourcesRoot: process.resourcesPath, userDataRoot: app.getPath("userData") },
    });
    const appearanceMainControl = createAssistantAppearanceMainControl({
      chooseImage: async (kind,signal) => {
        if (!launcherAssistantWindow || shutdownApproved) throw new Error("ASSISTANT_NOT_READY");
        return launcherAssistantWindow.chooseOperatorImage(kind,signal);
      },
      importImage: async (input,deliveryId) => {
        if (!launcherAssistantHost || shutdownApproved) throw new Error("ASSISTANT_NOT_READY");
        return launcherAssistantHost.importOperatorImage(input,deliveryId);
      },
      theme: async (request,signal) => launcherAssistantWindow
        ? launcherAssistantWindow.requestTheme(request,signal)
        : {schemaVersion:1,operation:request.operation,code:"unavailable"},
    });
    const mainControl: NonNullable<ConstructorParameters<typeof AssistantHost>[0]["mainControl"]> = (request,signal) => {
      if (request.action === "launcher_theme_get" || request.action === "launcher_theme_set" || request.action === "operator_image_upload")
        return appearanceMainControl(request,signal);
      if (request.action === "initial_migration_receipt") {
        const base = { schemaVersion: 1, projectId: request.projectId, category: request.category,
          operationId: request.operationId, readyForCutover: false };
        return projectConnection.withHistoryImport(request.projectId, async () => {
          let state: "queued" | "completed" | "partial" | "unknown" | "not_found" = initialMigrationStates.get(request.operationId) ?? "not_found";
          if (state === "not_found" && initialMigrationResults) {
            const stored = await initialMigrationResults.get(request.operationId);
            state = stored === "not_started" ? "unknown" : stored ?? "not_found";
          }
          // A re-registered project has a different opaque ID. Existing intents
          // may belong to that source, so a different hash is not proof of absence.
          if (state === "not_found" && (initialMigrationRecoveryUncertain || initialMigrationStates.size > 0)) state = "unknown";
          return { ...base, state, code: state };
        }).catch(() => ({ ...base, state: "unknown", code: "unknown" }));
      }
      if (request.action === "initial_migration_queue") {
        const base = { schemaVersion: 1, projectId: request.projectId, previewId: request.previewId,
          category: request.category, operationId: request.operationId, readyForCutover: false,
          ...(request.category === "knowledge_recovery" ? { originalSyncId: request.originalSyncId } : {}) };
        const host = launcherAssistantHost;
        if (!host || shutdownApproved) return Promise.resolve({ ...base, state: "rejected", code: "unavailable" });
        return projectConnection.withHistoryImport(request.projectId, async revision => {
          const prepared = await host.prepareInitialMigration(request, revision, signal);
          const previous = initialMigrationStates.get(request.operationId);
          if (prepared || (previous !== "completed" && previous !== "partial")) initialMigrationStates.set(request.operationId, prepared ? "queued" : "unknown");
          return prepared ? { ...base, state: "queued", code: "queued" } : { ...base, state: "unknown", code: "unknown" };
        }).catch(() => {
          const previous = initialMigrationStates.get(request.operationId);
          if (previous !== "completed" && previous !== "partial") initialMigrationStates.set(request.operationId, "unknown");
          return { ...base, state: "unknown", code: "unknown" };
        });
      }
      if (request.action === "history_import") {
        const host = launcherAssistantHost;
        if (!host || shutdownApproved) return Promise.resolve({ schemaVersion: 1, projectId: request.projectId,
          previewId: request.previewId, state: "rejected", code: "project_unavailable", readyForCutover: false });
        return projectConnection.withHistoryImport(request.projectId, revision => host.importHistory({
          projectId: request.projectId, previewId: request.previewId, turnId: request.turnId, revision, signal,
        }));
      }
      if (request.action === "affairs_sync") {
        const host = launcherAssistantHost;
        if (!host || shutdownApproved) return Promise.resolve(request.recoverSyncId !== undefined
          ? unknownAffairsSyncResult(request) : { ...unknownAffairsSyncResult(request),
            state: "rejected", code: "project_unavailable" });
        return projectConnection.withHistoryImport(request.projectId, revision => host.syncAffairs({
          projectId: request.projectId, previewId: request.previewId, turnId: request.turnId, revision, signal,
          ...(request.recoverSyncId !== undefined ? { recoverSyncId: request.recoverSyncId } : {}),
        }));
      }
      if (request.action === "episodic_sync") {
        const host = launcherAssistantHost;
        if (!host || shutdownApproved) return Promise.resolve(request.recoverSyncId !== undefined
          ? unknownEpisodicSyncResult(request) : { ...unknownEpisodicSyncResult(request),
            state: "rejected", code: "project_unavailable" });
        return projectConnection.withHistoryImport(request.projectId, revision => host.syncEpisodic({
          projectId: request.projectId, previewId: request.previewId, turnId: request.turnId, revision, signal,
          ...(request.recoverSyncId !== undefined ? { recoverSyncId: request.recoverSyncId } : {}),
          ...(request.resolveSyncId !== undefined ? { resolveSyncId: request.resolveSyncId, reviewToken: request.reviewToken } : {}),
        }));
      }
      return projectMainControl(request);
    };
    const resources = await resolveAssistantResources({ packaged: app.isPackaged, resourcesRoot: paths.resourcesRoot,
      developmentSourceRoot: paths.workspaceRoot, developmentPythonPath: app.isPackaged ? "" : desktopPythonPath(), env: desktopEnvironment() });
    if (shutdownApproved) return;
    let migrationPending = false;
    const migrationDialog: { current: AbortController | null } = { current: null };
    const showMigrationWait = () => {
      if (!migrationPending || migrationDialog.current || shutdownApproved) return;
      const controller = new AbortController();
      migrationDialog.current = controller;
      void dialog.showMessageBox({ type: "info", title: "个人助理正在准备",
        message: "正在处理首次迁移，个人助理将在处理完成后打开。",
        detail: "也可以打开 Launcher，或退出并安全停止迁移。",
        buttons: ["继续等待", "打开 Launcher", "退出"], cancelId: 0, noLink: true, signal: controller.signal,
      }).then(({ response }) => {
        if (controller.signal.aborted || shutdownApproved) return;
        if (response === 1) void requestOpenLauncherFromAssistant().catch(() => console.warn("ASSISTANT_LAUNCHER_UNAVAILABLE"));
        if (response === 2) { if (assistantOnly) { shutdownApproved = true; app.quit(); }
          else void requestDesktopShellExit().catch(() => console.warn("ASSISTANT_STOP_FAILED")); }
      }).catch(() => console.warn("ASSISTANT_STARTUP_DIALOG_FAILED"))
        .finally(() => { if (migrationDialog.current === controller) migrationDialog.current = null; });
    };
    showAssistantStartupWait = showMigrationWait;
    dismissAssistantStartupWait = () => migrationDialog.current?.abort();
    desktopTray ??= createAssistantTray(resources.sourceRoot, {
      open: () => { if (launcherAssistantWindow) void launcherAssistantWindow.open().catch(() => console.warn("ASSISTANT_WINDOW_FAILED"));
        else showMigrationWait(); },
      openLauncher: () => { void requestOpenLauncherFromAssistant().catch(() => {
        void dialog.showMessageBox({ type: "error", title: "Launcher 暂不可用",
          message: "未能打开项目管理，请确认选择的是可用的 Vibelution 项目目录后重试。" });
      }); },
      quit: () => { if (!assistantOnly) { void requestDesktopShellExit().catch(() => console.warn("ASSISTANT_STOP_FAILED")); return; }
        shutdownApproved = true; app.quit(); },
    });
    // Keep the new cold-start writer isolated while the complete packaged
    // migration and retirement acceptance is still being completed.
    const initialMigrationControl = process.env.VIBELUTION_INITIAL_MIGRATION_EXPERIMENT === "1";
    if (initialMigrationControl) {
      migrationPending = true;
      assistantMigrationPending = true;
      const waitTimer = setTimeout(() => { if (!desktopCliArgs.hiddenPresentation || pendingAssistantOpen?.show) showMigrationWait(); }, 1000);
      const profileRoot = join(paths.userDataRoot, "assistant", "profile");
      try {
        initialMigrationResults = new InitialMigrationResults(join(paths.userDataRoot, "assistant", "initial-migration-results"));
        const recovered = await recoverInitialMigrations({ registry: projectConnection,
        results: initialMigrationResults,
        targetProfile: profileRoot, sourceConfig: desktopLaunchSettings().configPath,
        targetConfig: async (operationId, registryDigest) => join(profileRoot, `.initial-migration-models-v1-${operationId}-${registryDigest}.toml`),
        verifyResult: (operationId, state) => verifyInitialMigrationResult({ targetProfile: profileRoot,
          sourceRoot: resources.sourceRoot, pythonPath: resources.pythonPath, pythonArguments: resources.pythonArguments,
          runtimeRoot: join(paths.userDataRoot, "assistant", "runtime"), env: resources.env, signal: launcherAssistantStartupAbort.signal }, operationId, state),
        sourceRoot: resources.sourceRoot, pythonPath: resources.pythonPath, pythonArguments: resources.pythonArguments,
        runtimeRoot: join(paths.userDataRoot, "assistant", "runtime"), env: resources.env, signal: launcherAssistantStartupAbort.signal });
        for (const item of recovered) initialMigrationStates.set(item.operationId, item.state);
      } catch {
        // Listing/receipt failures leave intents unknown; no writer is replayed.
        initialMigrationRecoveryUncertain = true;
        console.warn("ASSISTANT_INITIAL_MIGRATION_RECOVERY_UNAVAILABLE");
      } finally {
        migrationPending = false;
        assistantMigrationPending = false;
        showAssistantStartupWait = null;
        dismissAssistantStartupWait = null;
        clearTimeout(waitTimer);
        migrationDialog.current?.abort();
      }
    }
    if (shutdownApproved) return;
    await new Promise<void>((windowOpened, startupFailed) => {
      void projectConnection.start((snapshot, projectsSuspended) => {
        const host = new AssistantHost({
          profileRoot: join(paths.userDataRoot, "assistant", "profile"),
          runtimeRoot: join(paths.userDataRoot, "assistant", "runtime"),
          sourceRoot: resources.sourceRoot, pythonPath: resources.pythonPath, pythonArguments: resources.pythonArguments,
          env: resources.env, projects: snapshot.projects, projectSnapshot: snapshot, projectsSuspended,
          mainControl, appearanceControl: true, initialMigrationControl,
        });
        launcherAssistantHost = host;
        launcherAssistantWindow = new AssistantWindow(paths, host, () => shutdownApproved, requestOpenLauncherFromAssistant);
        let reminderDialogTail: Promise<unknown> = Promise.resolve();
        const showReminderFallback = (notice: { title: string; body: string }) => {
          const shown = reminderDialogTail.then(() => {
            if (shutdownApproved) throw new Error("ASSISTANT_STOPPED");
            if (!launcherAssistantWindow) throw new Error("ASSISTANT_WINDOW_UNAVAILABLE");
            return launcherAssistantWindow.showReminder(notice);
          });
          reminderDialogTail = shown.then(() => undefined, () => undefined);
          return shown;
        };
        stopLauncherAssistantReminders = startAssistantReminderPump({
          host,
          available: () => !shutdownApproved,
          notify: (notice, recoveredFallback, onClick, onFailure, onFallback, onLateFallback) => new Promise((resolve, reject) => {
            let settled = false;
            let resultChannel: "system_notification" | "attention_fallback" | "unknown" = "unknown";
            let lateFallbackStarted = false;
            const timeout = setTimeout(() => {
              if (!settled) { settled = true; reject(new Error("ASSISTANT_REMINDER_NOTIFICATION_UNKNOWN")); }
            }, 10_000);
            const fallback = () => {
              if (settled) {
                if (resultChannel === "attention_fallback" || lateFallbackStarted) return;
                lateFallbackStarted = true;
                console.warn("ASSISTANT_REMINDER_NOTIFICATION_FAILED");
                onLateFallback(() => showReminderFallback(notice).then(result => result.response === 0));
                return;
              }
              settled = true;
              resultChannel = "attention_fallback";
              clearTimeout(timeout);
              if (!recoveredFallback) console.warn("ASSISTANT_REMINDER_NOTIFICATION_FAILED");
              onFallback(showReminderFallback(notice).then(result => result.response === 0));
              resolve("attention_fallback");
            };
            if (recoveredFallback || !Notification.isSupported()) { fallback(); return; }
            try {
              const notification = new Notification({ title: notice.title, body: notice.body, silent: false });
              notification.on("click", onClick);
              notification.on("failed", fallback);
              notification.on("show", () => {
                if (!settled) { settled = true; resultChannel = "system_notification"; clearTimeout(timeout); resolve("system_notification"); }
              });
              nativeNotificationLifetime.retain(notification);
              notification.show();
            } catch { fallback(); }
          }),
          openAssistant: () => { void launcherAssistantWindow?.open({ show: true }).catch(() => console.warn("ASSISTANT_WINDOW_FAILED")); },
          onError: reason => {
            console.warn(reason === "notification" ? "ASSISTANT_REMINDER_NOTIFICATION_FAILED" : "ASSISTANT_REMINDER_TRANSPORT_FAILED");
            if (!shutdownApproved) void dialog.showMessageBox({
              type: "warning", title: "个人助理提醒暂不可用",
              message: reason === "notification"
                ? "系统通知未能显示，已有事务和发送记录仍会保留。"
                : "助理暂时无法连接提醒服务，已有事务和发送记录仍会保留。",
              buttons: ["确定"], noLink: true,
            }).catch(() => console.warn("ASSISTANT_REMINDER_WARNING_FAILED"));
          },
        });
        // The character can show starting/error state while native readiness
        // remains queued ahead of every authorization update.
        const show = !desktopCliArgs.hiddenPresentation || pendingAssistantOpen?.show === true;
        pendingAssistantOpen = null;
        void launcherAssistantWindow.open({ show }).then(windowOpened, startupFailed);
        return host;
      }).catch(error => {
        console.warn("ASSISTANT_START_FAILED");
        startupFailed(error);
      });
    });
  })();
  return launcherAssistantStarting;
}

async function stopLauncherAssistant(): Promise<void> {
  if (launcherAssistantStopping) return launcherAssistantStopping;
  dismissAssistantStartupWait?.();
  launcherAssistantStartupAbort.abort();
  const stopping = (async () => {
    const stoppingDialog = new AbortController();
    const waitTimer = assistantMigrationPending ? setTimeout(() => {
      void dialog.showMessageBox({ type: "info", title: "正在退出个人助理",
        message: "正在安全停止迁移，请稍候。",
        detail: "退出会等待迁移进程及其输出完全结束。", buttons: ["继续等待"], noLink: true,
        signal: stoppingDialog.signal }).catch(() => console.warn("ASSISTANT_STOP_DIALOG_FAILED"));
    }, 1000) : null;
    try {
      const stoppingReminders = stopLauncherAssistantReminders?.();
      const connection = launcherAssistantProjects;
      const stoppingProjects = connection
        ? (stoppingReminders ? stoppingReminders.then(() => connection.stop()) : connection.stop())
        : undefined;
      await launcherAssistantStarting?.catch(() => undefined);
      if (stoppingProjects) await stoppingProjects;
      else {
        await stopLauncherAssistantReminders?.();
        await launcherAssistantProjects?.stop();
      }
      stopLauncherAssistantReminders = null;
      launcherAssistantExitReady = true;
    } finally {
      if (waitTimer) clearTimeout(waitTimer);
      stoppingDialog.abort();
    }
  })();
  launcherAssistantStopping = stopping;
  try { await stopping; }
  catch (error) {
    // A later explicit exit must be able to retry the retained owner cleanup.
    if (launcherAssistantStopping === stopping) launcherAssistantStopping = null;
    throw error;
  }
}

async function exitDesktopShellProcess(): Promise<void> {
  await stopLauncherAssistant();
  app.exit(0);
}

ipcMain.handle(IPC_CHANNELS.assistantThemeResult, (event,payload:unknown) => {
  if (shutdownApproved || !launcherAssistantWindow) return false;
  return launcherAssistantWindow.acceptThemeResult(event,payload);
});

ipcMain.handle(IPC_CHANNELS.assistantInvoke, async (event, payload: unknown) => {
  if (shutdownApproved || !launcherAssistantWindow) throw new Error("ASSISTANT_NOT_READY");
  return await launcherAssistantWindow.invoke(event, payload);
});

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
  if (projectControlPlaneLaunchSettings !== null) return projectControlPlaneLaunchSettings;
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
  if (projectControlPlaneLaunchSettings !== null) {
    for (const key of Object.keys(baseEnv)) {
      if (["VIBELUTION_WORKSPACE_ROOT", "VIBELUTION_PYTHON_PATH", "PYTHON", "PYTHONPATH", "PYTHONHOME"].includes(key.toUpperCase())) delete (baseEnv as NodeJS.ProcessEnv)[key];
    }
  }
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
  workbenchNotificationServices = new WeakMap();
  const launcherDistRootInput = {
    resourcesRoot: paths.resourcesRoot,
    workspaceRoot: paths.workspaceRoot,
    packaged: app.isPackaged,
    env: desktopEnv
  };
  return new ElectronWindowProvider(
    paths,
    resolveLauncherWindowUrl(desktopEnv),
    resolveWorkbenchUrl(desktopEnv, bootstrap?.workbenchUrl),
    {
      createLauncherWindow,
      createWorkbenchWindow,
      createPetWindow,
      launcherContentVersion: () => resolveLauncherDistRoot(launcherDistRootInput),
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
            const url = window.webContents.getURL();
            return !isDesktopPetWindowUrl(url) && isLiveWorkbenchWindowUrl(url, workbenchOrigin);
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
      shouldBlockWorkbenchOpen: () => workbenchFailedCloseHandling || isWorkbenchStartBlockedByClose(
        hasBackgroundWorkbenchRetirement(paths.workspaceRoot), mainWorkbenchCloseStore.currentTransaction(),
        pendingWorkbenchCloseAck !== null),
      shouldInterceptInstanceClose: () => !shutdownApproved,
      onWorkbenchCloseRequest: () =>
        requestTransactionalWorkbenchClose(paths, bootstrap).catch((error: unknown) =>
          handleTransactionalWorkbenchCloseFailure(paths, bootstrap, error)
        ),
      onWorkbenchClosed: () =>
        acknowledgeTransactionalWorkbenchClose(paths, bootstrap).catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        }),
      onWorkbenchOpenRequest: () => startOrFocusWorkbenchFromProductEntryOnShell(),
      openExternalUrl: (url) => shell.openExternal(url),
      onInstanceCloseRequest: async (instanceId) => {
        try {
          const result = await orchestrateBranchInstanceLifecycle("stop", {
            schemaVersion: 1,
            path: "branch-instances/window-close",
            init: {
              method: "POST",
              body: { instanceId }
            }
          });
          if (!result.accepted || result.code) {
            const detail = String(result.message || result.code || "隔离实例后端仍未确认关闭").trim();
            notifyDesktopTray("Vibelution", `隔离工作区未关闭，窗口已保留：${detail.slice(0, 260)}`, "warning");
          }
        } catch (error: unknown) {
          const detail = error instanceof Error ? error.message : String(error);
          notifyDesktopTray("Vibelution", `隔离工作区未关闭，窗口已保留：${detail.slice(0, 260)}`, "warning");
          console.warn(error instanceof Error ? error.message : String(error));
        }
      },
      onWorkbenchFocusAttentionClear: (sender) => {
        workbenchNotificationServices.get(sender)?.service.clearAttention();
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
    void reclaimExpiredIsolatedStops()
      .catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      })
      .finally(() => {
        void launcherStateStore.refresh("reconcile_deadline");
      });
  }
});

launcherStateStore.subscribe((snapshot) => {
  reconcileDeadlineScheduler.schedule(projectControlPlaneAutomaticLifecycle ? snapshot.nextReconcileAt : undefined);
  windowProvider?.sendToLauncher(IPC_CHANNELS.launcherStateChanged, snapshot);
});

const CONVERSATION_BADGE_GLYPHS: Readonly<Record<number, readonly string[]>> = {
  1: ["  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"],
  2: [" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"],
  3: [" ### ", "#   #", "    #", " ### ", "    #", "#   #", " ### "],
  4: ["   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "],
  5: ["#####", "#    ", "#    ", "#### ", "    #", "#   #", " ### "],
  6: [" ### ", "#   #", "#    ", "#### ", "#   #", "#   #", " ### "],
  7: ["#####", "    #", "   # ", "  #  ", " #   ", " #   ", " #   "],
  8: [" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "],
  9: [" ### ", "#   #", "#   #", " ####", "    #", "#   #", " ### "]
};

function pngCrc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function pngChunk(type: string, data: Buffer): Buffer {
  const typeBytes = Buffer.from(type, "ascii");
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(pngCrc32(Buffer.concat([typeBytes, data])), 0);
  return Buffer.concat([length, typeBytes, data, crc]);
}

function createConversationBadgePng(count: number): Buffer {
  const safeCount = Math.max(1, Math.min(9, Math.round(count)));
  const size = 32;
  const rgba = Buffer.alloc(size * size * 4);
  const radiusSquared = 15 * 15;

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const dx = x - 16;
      const dy = y - 16;
      if (dx * dx + dy * dy > radiusSquared) {
        continue;
      }
      const offset = (y * size + x) * 4;
      rgba[offset] = 0x1f;
      rgba[offset + 1] = 0x29;
      rgba[offset + 2] = 0x37;
      rgba[offset + 3] = 0xff;
    }
  }

  const glyph = CONVERSATION_BADGE_GLYPHS[safeCount];
  const scale = 3;
  const glyphWidth = glyph[0].length * scale;
  const glyphHeight = glyph.length * scale;
  const originX = Math.floor((size - glyphWidth) / 2);
  const originY = Math.floor((size - glyphHeight) / 2);
  for (let row = 0; row < glyph.length; row += 1) {
    for (let column = 0; column < glyph[row].length; column += 1) {
      if (glyph[row][column] !== "#") {
        continue;
      }
      for (let y = 0; y < scale; y += 1) {
        for (let x = 0; x < scale; x += 1) {
          const pixelX = originX + column * scale + x;
          const pixelY = originY + row * scale + y;
          const offset = (pixelY * size + pixelX) * 4;
          rgba[offset] = 0xff;
          rgba[offset + 1] = 0xff;
          rgba[offset + 2] = 0xff;
          rgba[offset + 3] = 0xff;
        }
      }
    }
  }

  const scanlines = Buffer.alloc(size * (size * 4 + 1));
  for (let y = 0; y < size; y += 1) {
    const rowOffset = y * (size * 4 + 1);
    rgba.copy(scanlines, rowOffset + 1, y * size * 4, (y + 1) * size * 4);
  }

  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8;
  header[9] = 6;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    pngChunk("IHDR", header),
    pngChunk("IDAT", deflateSync(scanlines)),
    pngChunk("IEND", Buffer.alloc(0))
  ]);
}

function createConversationBadgeIcon(count: number) {
  return nativeImage.createFromBuffer(createConversationBadgePng(count));
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

function resolveConversationNotificationService(event: IpcMainInvokeEvent): ConversationNotificationService | null {
  const target = windowProvider?.notificationTargetForSender(event.sender, event.senderFrame?.url ?? "");
  if (!target) return null;
  const origin = new URL(event.senderFrame!.url).origin;
  const existing = workbenchNotificationServices.get(event.sender);
  if (existing?.origin === origin && existing.target.isLive()) return existing.service;
  const service = createConversationNotificationService({
    windowProvider: target,
    notificationSupported: () => Notification.isSupported(),
    createNotification: ({ title, body, onClick, onShow, onFailed }) => {
      const notification = new Notification({ title, body, silent: false });
      notification.on("click", onClick);
      notification.on("show", onShow);
      notification.on("failed", onFailed);
      nativeNotificationLifetime.retain(notification);
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
  workbenchNotificationServices.set(event.sender, { origin, service, target });
  return service;
}

function resolveHumanAttentionNotificationService(): HumanAttentionNotificationService {
  if (humanAttentionNotificationService !== null) {
    return humanAttentionNotificationService;
  }
  humanAttentionNotificationService = createHumanAttentionNotificationService({
    // The bridge reads the current window provider lazily, so a rebuilt
    // provider never strands the service on a stale window set.
    windowBridge: {
      sendToAssistantWindow: (channel, payload) =>
        windowProvider?.sendToPet(channel, payload) === true,
      isAssistantWindowVisible: () => windowProvider?.isPetVisible() === true,
      sendToWorkbench: (channel, payload) =>
        windowProvider?.sendToWorkbench(channel, payload) === true,
      focusWorkbench: () => windowProvider?.focusWorkbench() ?? Promise.resolve(),
      setWorkbenchAttention: (attention) => windowProvider?.setWorkbenchAttention(attention)
    },
    notificationSupported: () => Notification.isSupported(),
    createNotification: ({ title, body, onClick }) => {
      const notification = new Notification({ title, body, silent: false });
      notification.on("click", onClick);
      nativeNotificationLifetime.retain(notification);
      return notification;
    },
    openedChannel: IPC_CHANNELS.humanAttentionOpened,
    recordEvent: async (event) => {
      await recordElectronSupervisorEvent(launcherBootstrap, {
        ...event,
        fields: normalizeRuntimeSceneFields(event.fields)
      });
    }
  });
  return humanAttentionNotificationService;
}

async function resolveInitialWorkbenchUrl(paths: DesktopPaths, signal?: AbortSignal): Promise<string> {
  // T9: Electron main is the Launcher control plane. The Python :8765 service
  // is no longer spawned; the workbench URL is resolved through a no-console
  // Python bridge (env → ports.json → config → default).
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (pythonPath) {
    try {
      return await resolveWorkbenchUrlFromBridge({
        workspaceRoot: paths.workspaceRoot,
        pythonPath,
        operatorConfigPath: String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
        signal
      });
    } catch (error: unknown) {
      if (!signal?.aborted) console.warn(error instanceof Error ? error.message : String(error));
    }
  }
  return "";
}

async function bootstrapMainOwnedLauncher(
  paths: DesktopPaths,
  pendingWorkbenchUrl = resolveInitialWorkbenchUrl(paths)
): Promise<LauncherBootstrapResult | null> {
  const desktopEnv = desktopEnvironment();
  electronStartupStage = "control_plane_attach";
  const stageStartedAtMs = performance.now();
  const workbenchUrl = resolveWorkbenchUrl(desktopEnv, (await pendingWorkbenchUrl) || undefined);
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
  const openCloseGeneration = workbenchCloseGeneration;
  const openController = new AbortController();
  workbenchOpenControllers.add(openController);
  const assertCurrentOpen = (): void => {
    if (openCloseGeneration !== workbenchCloseGeneration || workbenchFailedCloseHandling
        || isWorkbenchStartBlockedByClose(hasBackgroundWorkbenchRetirement(paths.workspaceRoot),
          mainWorkbenchCloseStore.currentTransaction(), pendingWorkbenchCloseAck !== null)) {
      throw new Error("Workbench open superseded by close");
    }
  };
  const previousWorkbenchUrl = currentWorkbenchUrl;
  electronStartupStage = "workbench_navigation";
  const stageStartedAtMs = markWorkbenchOpenRequested();
  try {
    assertCurrentOpen();
    // A desktop action belongs to the already registered Electron session. Running
    // bootstrap again here can rotate the local control token that this session
    // uses to acknowledge actions, report window state, and close atomically.
    const payloadUrl = typeof payload.workbenchUrl === "string" ? payload.workbenchUrl.trim() : "";
    workbenchUrl = resolveWorkbenchUrl(desktopEnvironment(), payloadUrl || bootstrap.workbenchUrl);
    currentWorkbenchUrl = workbenchUrl;
    // A stale resolution can still name port 8000 after the backend died
    // (2026-09-29: "open window" created a Workbench window against a dead
    // backend and the window flashed away with no explanation). Prove the
    // backend is actually serving before navigating; when it is down, bring
    // it back through the existing lifecycle start path with a bounded wait.
    try {
      await ensureWorkbenchBackendReady({
        workspaceRoot: paths.workspaceRoot,
        workbenchUrl,
        startLifecycle: async () => {
          assertCurrentOpen();
          const result = await orchestrateLauncherLifecycle("start", { schemaVersion: 1, path: "open-workbench" },
            "operator", openController.signal, undefined, false, () => openCloseGeneration === workbenchCloseGeneration);
          assertCurrentOpen();
          if (!result.accepted) throw new Error(result.message || result.code || "Workbench start was not accepted.");
          return result;
        }
      });
    } catch (gateError: unknown) {
      assertCurrentOpen();
      const gateDetail = gateError instanceof Error ? gateError.message : String(gateError);
      await provider.presentWorkbenchErrorStatus({
        origin: safeOrigin(workbenchUrl),
        detail: gateDetail,
        ...(payload.present === false ? { present: false } : {})
      });
      throw gateError instanceof Error ? gateError : new Error(gateDetail);
    }
    assertCurrentOpen();
    const state = payload.present === false
      ? await provider.openOrFocusWorkbench(workbenchUrl, { present: false })
      : await provider.openOrFocusWorkbench(workbenchUrl);
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
  } finally {
    workbenchOpenControllers.delete(openController);
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
  if (state.role === "pet" || bootstrap === null || !desktopSessionMutations.accepts("window")) {
    return;
  }
  const managedRole: "launcher" | "workbench" = state.role;
  await desktopSessionMutations.enqueue("window", async () => {
    const desktopSessionId = currentDesktopSessionId(bootstrap);
    if (!desktopSessionRegistered) {
      electronStartupStage = "desktop_session_registration";
      const stageStartedAtMs = performance.now();
      const registration = inProcessDesktopSessionStore.register({
        desktopSessionId,
        capabilities: desktopSessionCapabilities(bootstrap)
      });
      desktopSessionRevision = registration.revision;
      desktopSessionRegistered = true;
      void desktopSessionMirror.register(async () => registerDesktopSession({
        ...(await resolveDesktopActionLoopContext(bootstrap)),
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
          desktopSessionId
        })
      };
      scheduleTelemetryWithoutWaiting(() => recordElectronSupervisorEvent(bootstrap, registrationEvent));
    }
    const result = inProcessDesktopSessionStore.reportWindow({
      desktopSessionId,
      role: managedRole,
      revision: desktopSessionRevision,
      state
    });
    desktopSessionRevision = result.revision;
    void desktopSessionMirror.mutate("window", async (mirrorRevision) => reportDesktopWindowState({
      ...(await resolveDesktopActionLoopContext(bootstrap)),
      role: managedRole,
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
          desktopSessionId,
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
        const result = inProcessDesktopSessionStore.heartbeat({
          desktopSessionId: currentDesktopSessionId(currentBootstrap),
          revision: desktopSessionRevision
        });
        desktopSessionRevision = result.revision;
        await desktopSessionMirror.mutate("heartbeat", async (mirrorRevision) => heartbeatDesktopSession({
          ...(await resolveDesktopActionLoopContext(currentBootstrap)),
          revision: mirrorRevision
        }));
      });
    } catch (error: unknown) {
      if (isRecoverableDesktopControlError(error) && windowProvider !== null) {
        try {
          await recoverDesktopControlContext(paths, currentBootstrap, windowProvider, "desktop_session_heartbeat");
        } catch (recoveryError: unknown) {
          const detail = recoveryError instanceof Error ? recoveryError.message : String(recoveryError);
          await recordElectronSupervisorEvent(currentBootstrap, {
            eventCode: "electron.desktop_session.heartbeat_recovery_failed",
            message: "Desktop session heartbeat control-context recovery failed; the next heartbeat will retry.",
            fields: {
              desktopSessionId: currentDesktopSessionId(currentBootstrap),
              stage: "desktop_session_heartbeat_recovery",
              error: detail.slice(0, 300)
            }
          });
          console.warn(detail);
        }
      } else {
        console.warn(error instanceof Error ? error.message : String(error));
      }
    } finally {
      desktopSessionHeartbeatRunning = false;
    }
  };
  desktopSessionHeartbeatTimer = setInterval(() => {
    void heartbeatOnce().catch((error: unknown) => {
      const detail = error instanceof Error ? error.message : String(error);
      console.warn(`desktop session heartbeat failed: ${detail}`);
      void recordElectronSupervisorEvent(launcherBootstrap, {
        eventCode: "electron.desktop_session.heartbeat_failed",
        message: "Desktop session heartbeat failed outside the controlled recovery path; the next heartbeat will retry.",
        fields: {
          stage: "desktop_session_heartbeat",
          error: detail.slice(0, 300)
        }
      });
    });
  }, DESKTOP_SESSION_HEARTBEAT_MS);
}

function stopDesktopSessionHeartbeat(): void {
  if (desktopSessionHeartbeatTimer !== null) {
    clearInterval(desktopSessionHeartbeatTimer);
    desktopSessionHeartbeatTimer = null;
  }
  desktopSessionHeartbeatRunning = false;
}

function currentDesktopControlOrigin(bootstrap: LauncherBootstrapResult, desktopEnv = desktopEnvironment()): string {
  // A verified lifecycle URL supersedes the process's initial bootstrap/env
  // hint after port relocation. Retained bridge callbacks may hold that old hint.
  return resolveWorkbenchUrl(
    currentWorkbenchUrl ? { ...desktopEnv, VIBELUTION_WORKBENCH_URL: currentWorkbenchUrl } : desktopEnv,
    launcherBootstrap?.workbenchUrl || bootstrap.workbenchUrl
  );
}

async function resolveDesktopActionLoopContext(
  bootstrap: LauncherBootstrapResult,
  options: { forceControlTokenRefresh?: boolean; signal?: AbortSignal } = {}
): Promise<DesktopActionLoopContext> {
  const desktopEnv = desktopEnvironment();
  const launcherOrigin = currentDesktopControlOrigin(bootstrap, desktopEnv);
  const workspaceRoot = createDesktopPathsForApp().workspaceRoot;
  if (backendControlTokenOwner === null || !backendControlTokenOwner.isForScope(workspaceRoot, launcherOrigin)) {
    backendControlTokenOwner = new BackendControlTokenOwner({
      workspaceRoot,
      launcherOrigin,
      readBackendIdentity: () => {
        const state = readLauncherStateFile(launcherStatePath(workspaceRoot));
        return { pid: Number(state.backendPid || 0), createTime: Number(state.backendCreateTime || 0) };
      },
      fetchControlToken: () => fetchLauncherControlToken({ launcherOrigin })
    });
  }
  const owner = backendControlTokenOwner;
  const controlToken = await owner.resolve({ forceRefresh: options.forceControlTokenRefresh, signal: options.signal });
  options.signal?.throwIfAborted();
  if (backendControlTokenOwner !== owner || !owner.isForScope(createDesktopPathsForApp().workspaceRoot, currentDesktopControlOrigin(bootstrap))) {
    throw new Error("Desktop control context scope changed during refresh.");
  }
  desktopActionContext = {
    launcherOrigin,
    controlToken,
    desktopSessionId: currentDesktopSessionId(bootstrap, desktopEnv)
  };
  return desktopActionContext;
}

function desktopControlContextForLocalClose(bootstrap: LauncherBootstrapResult): DesktopActionLoopContext {
  // Closing the old backend and writing local receipts must not wait for a
  // token endpoint that is already offline. Never use this snapshot for new work.
  if (desktopActionContext !== null) return desktopActionContext;
  const desktopEnv = desktopEnvironment();
  return {
    launcherOrigin: currentDesktopControlOrigin(bootstrap, desktopEnv),
    controlToken: String(desktopEnv.VIBELUTION_WEB_CONTROL_TOKEN || "").trim(),
    desktopSessionId: currentDesktopSessionId(bootstrap, desktopEnv)
  };
}

async function resolveRuntimeSceneBridge(bootstrap: LauncherBootstrapResult): Promise<RuntimeSceneBridge> {
  if (runtimeSceneBridge !== null) {
    return runtimeSceneBridge;
  }
  if (runtimeSceneBridgeOpening !== null) return runtimeSceneBridgeOpening;
  // Publish the construction owner before awaiting credentials. A cold offline
  // failure still reaches the caller's durable local fallback; concurrent first
  // records cannot construct different queues after that shared lookup settles.
  let opening!: Promise<RuntimeSceneBridge>;
  opening = Promise.resolve().then(async () => {
    const context = await resolveDesktopActionLoopContext(bootstrap);
    runtimeSceneBridge = new RuntimeSceneBridge({
      launcherOrigin: context.launcherOrigin,
      controlToken: context.controlToken,
      maxBufferedEvents: RUNTIME_SCENE_MAX_BUFFERED_EVENTS,
      resolveControlContext: () => resolveDesktopActionLoopContext(bootstrap),
      refreshControlToken: async () => (await resolveDesktopActionLoopContext(bootstrap, { forceControlTokenRefresh: true })).controlToken
    });
    return runtimeSceneBridge;
  }).finally(() => {
    if (runtimeSceneBridgeOpening === opening) runtimeSceneBridgeOpening = null;
  });
  runtimeSceneBridgeOpening = opening;
  return await opening;
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
  if (windowProvider === null) {
    void launcherAssistantWindow?.open().catch(() => console.warn("ASSISTANT_WINDOW_FAILED"));
    return;
  }
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
  workbenchCloseGeneration += 1;
  for (const controller of workbenchOpenControllers) controller.abort();
  const requestedAtMs = performance.now();
  const requestedAt = Date.now();
  const retireFrontendBuilds = captureFrontendBuildRetirement(paths.workspaceRoot);
  const fastCloseTiming = process.platform === "win32"
    ? { deadlineAt: requestedAt + WORKBENCH_CLOSE_BACKEND_WAIT_MS, forceAt: requestedAt + WORKBENCH_CLOSE_FORCE_AFTER_MS,
      background: { retireFrontendBuilds } }
    : undefined;
  await desktopLifecycleCoordinator.request("workbench_window_close", async () => {
    const projectionEpoch = launcherStateStore.beginMainLifecycle("force-stop");
    const preparationStartedAtMs = performance.now();
    const queuedMs = Math.max(0, Math.round(preparationStartedAtMs - requestedAtMs));
    const desktopSessionId = currentDesktopSessionId(bootstrap, desktopEnvironment());
    // Explicit project close interrupts work and attempts saving immediately.
    // A status probe is advisory and must never consume the close budget.
    const activeWorkState: ActiveWorkProbeState = "unknown";
    const activeWorkProbeMs = 0;
    let transaction = mainWorkbenchCloseStore.submit({
      mode: "force",
      requestId: randomUUID(),
      reason: "workbench_window_close",
      activeWorkState
    });
    pendingWorkbenchCloseAck = {
      closeId: transaction.closeId,
      desktopSessionId,
      requestedAtMs,
      ...(fastCloseTiming?.background ? { projectionEpoch } : {})
    };
    if (fastCloseTiming?.background) {
      // Admission persists stopping and captures exact resources. The window
      // ACK is independent of their eventual, strictly verified retirement.
      const admissionDeadline = createDesktopShellExitDeadline(Math.max(1, fastCloseTiming.deadlineAt - Date.now()));
      let admissionNeedsRetry = false;
      try {
        await withDesktopShellExitTimeout((signal) => stopWorkbenchBackend(paths, bootstrap, transaction, signal, fastCloseTiming),
          admissionDeadline, "workbench close admission");
      } catch (error: unknown) {
        if (!isWorkbenchCloseControlFetchFailure(error)) {
          mainWorkbenchCloseStore.fail(transaction.closeId, "backend_stop_admission_failed",
            error instanceof Error ? error.message : String(error));
          // No window close was authorized yet. A native window close request
          // will enter the failure handler; an action with no window must not
          // leave a phantom acknowledgement that blocks every future start.
          workbenchFailedCloseHandling = provider.isWorkbenchCloseInFlight();
          if (!workbenchFailedCloseHandling && pendingWorkbenchCloseAck?.closeId === transaction.closeId) {
            pendingWorkbenchCloseAck = null;
          }
          throw error;
        }
        // A timeout does not prove that the stop was admitted. Keep the same
        // transaction pending and retry after closing the window; never claim
        // closure from the missing acknowledgement.
        admissionNeedsRetry = true;
      } finally {
        admissionDeadline.dispose();
      }
      if (!launcherStateStore.markMainRetirementPending(projectionEpoch)) {
        mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "A newer lifecycle superseded this close.");
        if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
        return;
      }
      transaction = mainWorkbenchCloseStore.authorizeWindowBeforeBackendStopped(transaction.closeId);
      const ownedStop = (async (): Promise<void> => {
        let admissionPendingReported = false;
        while (admissionNeedsRetry && launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) {
          await new Promise<void>((resolve) => setTimeout(resolve, 250));
          if (!launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) break;
          // The original timed-out request may have admitted the exact owned
          // retirement after its caller stopped waiting. Join it rather than
          // starting a second stop that could supersede its generation.
          if (getBackgroundWorkbenchRetirement(paths.workspaceRoot)?.status === "pending") {
            admissionNeedsRetry = false;
            break;
          }
          const retryStarted = Date.now();
          const retryDeadline = createDesktopShellExitDeadline(WORKBENCH_CLOSE_BACKEND_WAIT_MS);
          try {
            await withDesktopShellExitTimeout((signal) => stopWorkbenchBackend(paths, bootstrap, transaction, signal, {
              deadlineAt: retryStarted + WORKBENCH_CLOSE_BACKEND_WAIT_MS,
              forceAt: retryStarted + WORKBENCH_CLOSE_FORCE_AFTER_MS,
              background: { retireFrontendBuilds }
            }, () => launcherStateStore.isMainLifecycleCurrent(projectionEpoch)), retryDeadline, "background close admission");
            admissionNeedsRetry = false;
          } catch (error: unknown) {
            if (getBackgroundWorkbenchRetirement(paths.workspaceRoot)?.status === "pending") {
              admissionNeedsRetry = false;
            } else if (!isWorkbenchCloseControlFetchFailure(error)) {
              launcherStateStore.releaseMainRetirementPending(projectionEpoch);
              const failed = mainWorkbenchCloseStore.fail(transaction.closeId, "backend_stop_admission_failed",
                error instanceof Error ? error.message : String(error));
              if (failed.windowAcknowledged && pendingWorkbenchCloseAck?.closeId === transaction.closeId) {
                await acknowledgeTransactionalWorkbenchClose(paths, bootstrap);
              }
              notifyDesktopTray("Vibelution", "后台回收未完成；请查看 Launcher 状态后重试。", "warning");
              return;
            } else if (!admissionPendingReported) {
              admissionPendingReported = true;
              recordSupervisorEventFallbackLocally({ eventCode: "electron.workbench_close.background_admission_pending",
                message: "Workbench closed; backend retirement admission remains unconfirmed.",
                fields: { closeId: transaction.closeId, detail: String(error instanceof Error ? error.message : error).slice(0, 300) } });
            }
          } finally {
            retryDeadline.dispose();
          }
        }
        if (!launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) {
          launcherStateStore.releaseMainRetirementPending(projectionEpoch);
          mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "A newer lifecycle superseded this close.");
          if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
          return;
        }
        const owner = getBackgroundWorkbenchRetirement(paths.workspaceRoot);
        if (owner && await owner.completion !== "closed") {
          launcherStateStore.releaseMainRetirementPending(projectionEpoch);
          mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "Background retirement was superseded.");
          if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
          return;
        }
        if (!owner) {
          let buildsRetired = false;
          let buildFlight: Promise<boolean> | null = null;
          const retireCapturedBuilds = (): Promise<boolean> => {
            if (buildsRetired) return Promise.resolve(true);
            if (buildFlight) return buildFlight;
            const pending = Promise.resolve().then(retireFrontendBuilds).then((confirmed) => {
              if (confirmed) buildsRetired = true;
              return confirmed;
            });
            buildFlight = pending;
            const releaseFlight = (): void => { if (buildFlight === pending) buildFlight = null; };
            void pending.then(releaseFlight, releaseFlight);
            return pending;
          };
          while (launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) {
            const readDeadline = createDesktopShellExitDeadline(1000);
            let settled = false;
            try {
              const results = await withDesktopShellExitTimeout((signal) => Promise.all([waitForWorkbenchBackendSettledForWindowClose({
                readStatus: async () => readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot), timeoutMs: 1000, signal
              }), retireCapturedBuilds()]), readDeadline, "background close readback");
              settled = results[0];
            } catch {
              // Unknown or timed-out observations retain stopping and retry.
            } finally {
              readDeadline.dispose();
            }
            if (settled && buildsRetired) break;
            await new Promise<void>((resolve) => setTimeout(resolve, 250));
          }
        }
        if (!launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) {
          mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "A newer lifecycle superseded the background close.");
          if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
          return;
        }
        const completed = mainWorkbenchCloseStore.backendStopped(transaction.closeId);
        if (completed.phase === "succeeded") await acknowledgeTransactionalWorkbenchClose(paths, bootstrap);
      })();
      workbenchCloseBackendStopInFlight = ownedStop;
      void ownedStop.catch((error: unknown) => {
        recordSupervisorEventFallbackLocally({ eventCode: "electron.workbench_close.background_pending",
          message: "Workbench window closed; background retirement still requires reconciliation.",
          fields: { closeId: transaction.closeId, detail: String(error instanceof Error ? error.message : error).slice(0, 300) } });
      }).finally(() => {
        if (workbenchCloseBackendStopInFlight === ownedStop) workbenchCloseBackendStopInFlight = null;
      });
      const windowState = await provider.approveWorkbenchCloseOnce({ deadlineAt: requestedAt + WORKBENCH_CLOSE_TOTAL_WAIT_MS });
      if (windowState?.open === true) {
        notifyDesktopTray("Vibelution", "工作台窗口未能关闭，后台仍在处理；完成后可重试。", "warning");
        // Do not release the start gate while the captured backend is still
        // being retired. Once it settles, surface the failed window close and
        // allow a fresh explicit retry without claiming window acknowledgement.
        void ownedStop.then(() => {
          const current = mainWorkbenchCloseStore.get(transaction.closeId);
          if (current?.phase === "failed" && pendingWorkbenchCloseAck?.closeId === transaction.closeId) {
            pendingWorkbenchCloseAck = null;
          }
          if (current && current.phase !== "succeeded" && current.phase !== "failed"
              && launcherStateStore.isMainLifecycleCurrent(projectionEpoch)) {
            mainWorkbenchCloseStore.fail(transaction.closeId, "window_close_failed", "Workbench window remains open.");
            launcherStateStore.releaseMainRetirementPending(projectionEpoch);
            if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
          }
        }).catch(() => undefined);
        return;
      }
      // No BrowserWindow means no 'closed' event will arrive. Reuse the same
      // acknowledgement only after the provider confirms the window is absent.
      if (windowState?.open === false && pendingWorkbenchCloseAck?.closeId === transaction.closeId
          && !transaction.windowAcknowledged) {
        await acknowledgeTransactionalWorkbenchClose(paths, bootstrap);
      }
      return;
    }
    const closeDeadline = createDesktopShellExitDeadline(fastCloseTiming
      ? Math.max(1, fastCloseTiming.deadlineAt - Date.now()) : 30_000);
    let backendStopMs = 0;
    let readbackMs = 0;
    const backendStopFlight = withDesktopShellExitTimeout(async (signal): Promise<boolean> => {
      recordSupervisorEventFallbackLocally({
        eventCode: "electron.workbench_close.backend_stopping",
        message: "Electron is stopping the workbench backend.",
        fields: {
          closeId: transaction.closeId,
          requestId: transaction.requestId ?? "",
          desktopSessionId,
          operatorIntent: transaction.mode === "force" ? "force_close" : "close",
          activeWorkState: transaction.activeWorkState,
          mode: transaction.mode,
          queuedMs,
          activeWorkProbeMs
        }
      });
      signal.throwIfAborted();
      const stopStartedAtMs = performance.now();
      try {
        const [, buildsRetired] = await Promise.all([
          stopWorkbenchBackend(paths, bootstrap, transaction, signal, fastCloseTiming),
          retireFrontendBuilds()
        ]);
        if (!buildsRetired) throw new Error("Owned frontend build processes did not retire before window authorization.");
      } finally {
        backendStopMs = Math.max(0, Math.round(performance.now() - stopStartedAtMs));
        recordSupervisorEventFallbackLocally({
          eventCode: "electron.workbench_close.backend_stop_settled",
          message: "Workbench backend stop returned; closure still requires the final state readback.",
          fields: { closeId: transaction.closeId, backendStopMs, aborted: signal.aborted }
        });
      }
      const readbackStartedAtMs = performance.now();
      const settled = await waitForWorkbenchBackendSettledForWindowClose({
        readStatus: async () => readRuntimeManagerLauncherStatusSummary(paths.workspaceRoot),
        timeoutMs: closeDeadline.remainingMs(),
        signal
      });
      readbackMs = Math.max(0, Math.round(performance.now() - readbackStartedAtMs));
      return settled;
    }, closeDeadline, "workbench close");
    workbenchCloseBackendStopInFlight = backendStopFlight.then((settled) => {
      if (!settled) {
        throw new Error("Workbench backend did not settle closed before window authorization.");
      }
    });
    const ownedBackendStop = workbenchCloseBackendStopInFlight;
    try {
      await ownedBackendStop;
    } catch (error: unknown) {
      mainWorkbenchCloseStore.fail(
        transaction.closeId,
        "backend_stop_timeout",
        error instanceof Error ? error.message : String(error)
      );
      throw error;
    } finally {
      closeDeadline.dispose();
      if (workbenchCloseBackendStopInFlight === ownedBackendStop) {
        workbenchCloseBackendStopInFlight = null;
      }
    }
    if (!launcherStateStore.commitVerifiedMainClosed(projectionEpoch)) {
      mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "A newer main lifecycle intent superseded this close.");
      return;
    }
    transaction = mainWorkbenchCloseStore.backendStopped(transaction.closeId);
    recordSupervisorEventFallbackLocally({
      eventCode: "electron.workbench_close.window_authorized",
      message: "Workbench backend closed; Electron is requesting the final window close.",
      fields: {
        closeId: transaction.closeId,
        desktopSessionId,
        phase: transaction.phase,
        queuedMs,
        activeWorkProbeMs,
        backendStopMs,
        readbackMs,
        elapsedMs: Math.max(0, Math.round(performance.now() - requestedAtMs))
      }
    });
    const windowState = await provider.approveWorkbenchCloseOnce(fastCloseTiming
      ? { deadlineAt: requestedAt + WORKBENCH_CLOSE_TOTAL_WAIT_MS } : {});
    if (windowState?.open === true) {
      mainWorkbenchCloseStore.fail(transaction.closeId, "window_close_failed", "Workbench window remains open.");
      if (pendingWorkbenchCloseAck?.closeId === transaction.closeId) pendingWorkbenchCloseAck = null;
      throw new Error("Workbench window remains open.");
    }
    if (windowState?.open === false && pendingWorkbenchCloseAck?.closeId === transaction.closeId
        && !transaction.windowAcknowledged) {
      await acknowledgeTransactionalWorkbenchClose(paths, bootstrap);
    }
  });
}

async function stopWorkbenchBackend(
  paths: DesktopPaths,
  bootstrap: LauncherBootstrapResult,
  transaction: MainWorkbenchCloseTransaction,
  signal?: AbortSignal,
  fastCloseTiming?: WorkbenchCloseTiming,
  lifecycleCurrent?: () => boolean
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
    // A force close is an explicitly confirmed destructive operator intent and
    // keeps the original supersede semantics; a normal window close must not
    // abort an in-flight restart.
  }, transaction.mode === "force" ? "operator" : "window-close", signal, fastCloseTiming, false, lifecycleCurrent);
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
      recordSupervisorEventFallbackLocally({
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
  if (transaction === null) {
    pendingWorkbenchCloseAck = null;
    return;
  }
  if (pending.projectionEpoch !== undefined && !launcherStateStore.isMainLifecycleCurrent(pending.projectionEpoch)) {
    pendingWorkbenchCloseAck = null;
    if (transaction.phase !== "succeeded" && transaction.phase !== "failed") {
      mainWorkbenchCloseStore.fail(transaction.closeId, "lifecycle_intent_superseded", "A newer lifecycle superseded the window ACK.");
    }
    return;
  }
  const wasAcknowledged = transaction.windowAcknowledged === true;
  const settled = mainWorkbenchCloseStore.windowClosed(transaction.closeId);
  if (settled.phase === "background_closing") {
    if (!wasAcknowledged) {
      try { notifyDesktopTray("Vibelution", "工作台窗口已关闭，后台仍在回收。可在 Launcher 查看“停止中”状态。"); }
      catch { console.warn("WORKBENCH_CLOSE_NOTICE_FAILED"); }
    }
    recordSupervisorEventFallbackLocally({ eventCode: "electron.workbench_close.window_closed_backend_pending",
      message: "Workbench window closed; owned backend retirement remains pending.",
      fields: { closeId: settled.closeId, workspaceRoot: paths.workspaceRoot } });
    return;
  }
  if (settled.phase === "succeeded" && pending.projectionEpoch !== undefined
    && !launcherStateStore.commitVerifiedMainClosed(pending.projectionEpoch)) return;
  pendingWorkbenchCloseAck = null;
  const context = desktopControlContextForLocalClose(bootstrap);
  if (settled.phase === "failed") {
    recordSupervisorEventFallbackLocally({
      eventCode: "electron.workbench_close.window_closed_after_failure",
      message: "Workbench window closed after the close transaction failed; backend outcome remains failed.",
      fields: {
        closeId: settled.closeId,
        desktopSessionId: context.desktopSessionId,
        failureCode: settled.failureCode ?? "",
        failureMessage: (settled.message ?? "").slice(0, 300),
        workspaceRoot: paths.workspaceRoot,
        elapsedMs: Math.max(0, Math.round(performance.now() - pending.requestedAtMs))
      }
    });
    return;
  }
  writeWorkbenchCloseCanarySummary(paths, {
    closeId: transaction.closeId,
    desktopSessionId: context.desktopSessionId,
    desktopSessionRevision,
    controlToken: context.controlToken
  });
  recordSupervisorEventFallbackLocally({
    eventCode: "electron.workbench_close.completed",
    message: "Electron confirmed the Workbench closed after the backend stopped.",
    fields: {
      closeId: transaction.closeId,
      desktopSessionId: context.desktopSessionId,
      desktopSessionRevision,
      workspaceRoot: paths.workspaceRoot,
      elapsedMs: Math.max(0, Math.round(performance.now() - pending.requestedAtMs))
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
  workbenchFailedCloseHandling = true;
  let retryScheduled = false;
  try {
    const message = error instanceof Error ? error.message : String(error);
    recordSupervisorEventFallbackLocally({
      eventCode: "electron.workbench_close.failed",
      message: "Workbench close transaction failed before Electron window authorization.",
      fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
    });
    const provider = windowProvider;
    if (provider === null) {
      console.warn(message);
      return;
    }
    const closeFailedWindow = async (): Promise<void> => {
      const state = await provider.approveWorkbenchCloseOnce();
      const failed = mainWorkbenchCloseStore.currentTransaction();
      if (state.open === false && failed?.phase === "failed" && pendingWorkbenchCloseAck?.closeId === failed.closeId) {
        await acknowledgeTransactionalWorkbenchClose(paths, bootstrap);
      } else if (state.open && failed?.phase === "failed" && pendingWorkbenchCloseAck?.closeId === failed.closeId) {
        pendingWorkbenchCloseAck = null;
        notifyDesktopTray("Vibelution", "工作台窗口未能关闭，后台回收也未完成；可检查状态后重试。", "warning");
      }
    };
    if (isWorkbenchCloseControlFetchFailure(error)) {
      recordSupervisorEventFallbackLocally({
        eventCode: "electron.workbench_close.fail_open_destroy",
        message: "Workbench close control fetch failed; Electron is destroying the window.",
        fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
      });
      await closeFailedWindow();
      return;
    }
    const retry = await confirmWorkbenchCloseRetry(provider, message);
    if (!retry) {
      recordSupervisorEventFallbackLocally({
        eventCode: "electron.workbench_close.fail_open_user_declined",
        message: "Workbench close transaction failed and retry was declined; closing the window while the backend may keep running.",
        fields: { error: message.slice(0, 300), workspaceRoot: paths.workspaceRoot }
      });
      await closeFailedWindow();
      return;
    }
    setTimeout(() => {
      const retry = requestTransactionalWorkbenchClose(paths, bootstrap);
      workbenchFailedCloseHandling = false;
      void retry.catch((retryError: unknown) =>
        handleTransactionalWorkbenchCloseFailure(paths, bootstrap, retryError)
      );
    }, 0);
    retryScheduled = true;
  } finally {
    if (!retryScheduled) workbenchFailedCloseHandling = false;
  }
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
    || !["backend_closing", "background_closing"].includes(transaction.phase)
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
      const bootstrap = launcherBootstrap;
      if (bootstrap === null) {
        return { state: "unknown", message: "Launcher bootstrap is not available." };
      }
      return await withDesktopShellExitTimeout(
        async (signal) => {
          const context = await resolveDesktopActionLoopContext(bootstrap, { signal });
          return await fetchLauncherActiveWorkStatus({ ...context, signal });
        },
        ACTIVE_WORK_STATUS_TIMEOUT_MS,
        "resolve launcher active work for force authorization"
      );
    },
    confirm: confirmLauncherForceLifecycle,
    record: async (authorization) => {
      const event = {
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
      };
      if (preconfirmedCloseAuthorization(input.instanceId, input.payload)) {
        recordSupervisorEventFallbackLocally(event);
      } else {
        await recordElectronSupervisorEvent(launcherBootstrap, event);
      }
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
      const context = desktopControlContextForLocalClose(bootstrap);
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

async function stopOwnedPythonLauncherService(signal?: AbortSignal): Promise<LauncherServiceStopResult> {
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
    launcherBackendPid: launcherBootstrap?.launcherBackendPid ?? 0,
    signal
  });
}

function runJoinedMainRuntimeShutdown(operation: () => Promise<void>): Promise<void> {
  if (mainRuntimeShutdownInFlight !== null) {
    return mainRuntimeShutdownInFlight;
  }
  const flight = Promise.resolve().then(operation);
  mainRuntimeShutdownInFlight = flight;
  void flight.then(
    () => {
      if (mainRuntimeShutdownInFlight === flight) mainRuntimeShutdownInFlight = null;
    },
    () => {
      if (mainRuntimeShutdownInFlight === flight) mainRuntimeShutdownInFlight = null;
    }
  );
  return flight;
}

async function stopManagedRuntime(signal?: AbortSignal): Promise<void> {
  return await runJoinedMainRuntimeShutdown(async () => {
    signal?.throwIfAborted();
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
    const lifecycleSignal = signal
      ? AbortSignal.any([signal, lease.signal])
      : lease.signal;
    const mutation = await launcherLifecycleSupervisor.executeMutation({
      lease,
      mutate: async () => await runWorkbenchLifecycle({
        workspaceRoot: paths.workspaceRoot,
        pythonPath,
        operatorConfigPath:
          launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
        operation: "shutdown",
        signal: lifecycleSignal
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
      throw new Error("Managed runtime shutdown was superseded before closure could be verified.");
    }
    if (!mutation.value.accepted) {
      throw new Error(mutation.value.message || mutation.value.code || "Managed runtime shutdown was not accepted.");
    }
  });
}

function desktopPythonPath(): string {
  const desktopEnv = desktopEnvironment();
  return String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
}

/**
 * State-refresh driven registry SSOT repair: adopt live backends sitting on
 * missing/terminal registry rows, settle rows whose registered identity is
 * confirmed dead, sweep dead keys whose worktree is gone, and write Electron
 * window truth back into the registry's windowPid. Refresh callers can use it
 * fire-and-forget; start waits when it must verify an adopted generation. The
 * reconciler is mutex-guarded and cooldown-limited, and a failure must never
 * fail the refresh that triggered it.
 * Skipped once shutdown is approved so it cannot fight the shutdown harvest.
 */
function scheduleRegistryReconciliation(branchInstances: unknown): Promise<void> {
  if (shutdownApproved) {
    return Promise.resolve();
  }
  return reconcileRegistryWithObservation({
    branchInstances,
    pythonPath: desktopPythonPath() || undefined,
    // Electron window truth is authoritative for instance window pids. Attach
    // it only while a window provider exists: before that, an empty truth
    // would be misread as "every window closed" and clear live pids.
    ...(windowProvider ? { instanceWindowStates: currentLauncherWindowTruth().instances } : {})
  }).then(() => undefined).catch((error: unknown) => {
    console.warn(error instanceof Error ? error.message : String(error));
  });
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

async function packagedDesktopShellIsStale(): Promise<boolean> {
  try {
    return (await inspectCurrentDesktopShell()).stale;
  } catch {
    return true;
  }
}

async function inspectCurrentDesktopShellLaunchReadiness(signal?: AbortSignal): Promise<DesktopShellLaunchReadiness> {
  const pythonPath = desktopPythonPath();
  if (!pythonPath) throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to inspect the desktop shell");
  return await inspectDesktopShellLaunchReadiness({
    workspaceRoot: createDesktopPathsForApp().workspaceRoot,
    pythonPath,
    signal
  });
}

async function scheduleCurrentDesktopShellRefresh(
  thenLifecycle: string,
  options: { force?: boolean; shellKind?: "packaged" | "unpackaged" } = {}
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
    force: options.force === true,
    shellKind: options.shellKind
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
    // A usable shell need not wait for frontend source scans or packaged
    // frontend hashes. Full advisory freshness stays with the existing watch
    // and status paths; only a launch blocker enters automatic replacement.
    const readiness = await inspectCurrentDesktopShellLaunchReadiness();
    if (!readiness.launchBlocking) {
      return false;
    }
    // Readiness deliberately omits refresh cooldown state. Keep the complete
    // status check before the guarded update can prepare or stop anything.
    status = await inspectCurrentDesktopShell();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `检查桌面壳版本失败，继续使用当前壳：${detail.slice(0, 220)}`, "warning");
    return false;
  }
  if (!status.launchBlocking) {
    // The blocking condition may have cleared while the full probe ran.
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
  try {
    // Automatic freshness checks never authorize interrupting active work.
    // Reuse the guarded update transaction: prepare, recheck, confirm stops,
    // then schedule replacement and exit. A failed stop must retain this shell.
    // forceRefresh stays off so the refresh cooldown is respected: after a
    // failed rebuild the automatic path must not stop the workspace again
    // during the cooldown window (explicit operator updates still bypass).
    const result = await restartLauncherToLatestBuild(false, thenLifecycle, { forceRefresh: false });
    if (!result.accepted && result.message) {
      notifyDesktopTray("Vibelution", result.message, "warning");
    }
    return result.accepted;
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    notifyDesktopTray("Vibelution", `桌面壳自动更新未完成，保留当前壳：${detail.slice(0, 220)}`, "warning");
    return false;
  }
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

function trustedIpcOrigins(event?: IpcMainInvokeEvent): string[] {
  const desktopEnv = desktopEnvironment();
  const workbenchUrl = currentWorkbenchUrl || resolveWorkbenchUrl(desktopEnv, launcherBootstrap?.workbenchUrl);
  return Array.from(
    new Set([
      launcherAppOriginFor(resolveLauncherWindowUrl(desktopEnv)),
      new URL(workbenchUrl).origin,
      ...(event?.senderFrame && event.senderFrame === event.sender.mainFrame
        ? [windowProvider?.trustedWorkbenchOrigin(event.sender, event.senderFrame.url) ?? ""].filter(Boolean)
        : [])
    ])
  );
}

async function stopMainRuntimeForApprovedShutdown(
  interruptActiveWork = false,
  signal?: AbortSignal
): Promise<void> {
  return await runJoinedMainRuntimeShutdown(async () => {
    const result = await orchestrateLauncherLifecycle("shutdown", {
      schemaVersion: 1,
      path: "desktop-shell-shutdown",
      init: {
        method: "POST",
        body: { operatorIntent: "desktop_shell_shutdown" }
      }
    }, interruptActiveWork ? "operator-restart" : "operator", signal);
    if (!result.accepted) {
      throw new Error(result.message || result.code || "Launcher shutdown was not accepted.");
    }
  });
}

async function captureShutdownIsolatedInstanceIds(deadline: DesktopShellExitDeadline): Promise<string[]> {
  if (launcherBootstrap === null) {
    return [];
  }
  const fallbackSnapshot = launcherStateStore.snapshot();
  const [snapshotResult, listedResult, registryResult] = await Promise.allSettled([
    withDesktopShellExitTimeout(
      () => launcherStateStore.refresh("desktop_shell_exit"),
      deadline,
      "refresh isolated instances for desktop shell exit"
    ),
    withDesktopShellExitTimeout(
      async (signal) => {
        const context = await resolveTrayControlContextOrLoopback();
        signal.throwIfAborted();
        return await fetchLauncherBranchInstances({
          ...context,
          requestTimeoutMs: Math.max(1, Math.min(8_000, deadline.remainingMs()))
        });
      },
      deadline,
      "fetch isolated instances for desktop shell exit"
    ),
    withDesktopShellExitTimeout(
      () => readRegistry(instancesRegistryPath()),
      deadline,
      "read isolated instance registry for desktop shell exit"
    )
  ]);
  const stateIds = snapshotResult.status === "fulfilled"
    ? captureShutdownInstanceIds(snapshotResult.value.instances)
    : captureShutdownInstanceIds(fallbackSnapshot.instances);
  const listedIds = listedResult.status === "fulfilled"
    ? captureRunningInstanceIds(listedResult.value).filter((instanceId) => instanceId !== "main")
    : [];
  const registryIds = registryResult.status === "fulfilled"
    ? captureShutdownInstanceIds(registryEntriesToShutdownInstanceSnapshots(registryResult.value.instances, knownPidIsAlive))
    : [];
  if (snapshotResult.status === "rejected") {
    console.warn(snapshotResult.reason instanceof Error ? snapshotResult.reason.message : String(snapshotResult.reason));
  }
  if (listedResult.status === "rejected") {
    console.warn(listedResult.reason instanceof Error ? listedResult.reason.message : String(listedResult.reason));
  }
  if (registryResult.status === "rejected") {
    console.warn(registryResult.reason instanceof Error ? registryResult.reason.message : String(registryResult.reason));
  }
  return Array.from(new Set([...stateIds, ...listedIds, ...registryIds]));
}

async function recordDesktopExitEvent(
  deadline: DesktopShellExitDeadline,
  event: RuntimeSceneElectronEvent
): Promise<void> {
  recordSupervisorEventFallbackLocally({
    ...event,
    fields: {
      ...event.fields,
      budgetConsumedMs: deadline.budgetMs - deadline.remainingMs(),
      budgetRemainingMs: deadline.remainingMs()
    }
  });
}

async function joinWorkbenchCloseBackendStop(deadline: DesktopShellExitDeadline): Promise<boolean> {
  const stop = workbenchCloseBackendStopInFlight;
  if (stop === null) return false;
  await withDesktopShellExitTimeout(
    () => stop,
    deadline,
    "join workbench close backend stop"
  );
  return true;
}

async function stopIsolatedInstancesForApprovedShutdown(
  interruptActiveWork = false,
  sharedDeadline?: DesktopShellExitDeadline
): Promise<void> {
  const ownsDeadline = sharedDeadline === undefined;
  const deadline = sharedDeadline ?? createDesktopShellExitDeadline();
  try {
    await stopIsolatedInstancesWithDeadline(interruptActiveWork, deadline);
  } finally {
    if (ownsDeadline) deadline.dispose();
  }
}

async function stopIsolatedInstancesWithDeadline(
  interruptActiveWork: boolean,
  deadline: DesktopShellExitDeadline
): Promise<void> {
  let instanceIds: string[] = [];
  try {
    instanceIds = await captureShutdownIsolatedInstanceIds(deadline);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    console.warn(`Unable to enumerate isolated instances for desktop shell exit: ${detail}`);
    throw new Error(`Unable to enumerate isolated instances for desktop shell exit: ${detail}`);
  }
  if (!instanceIds.length) {
    return;
  }

  await recordDesktopExitEvent(deadline, {
    eventCode: "electron.isolated_instances.stop_all_requested",
    message: "All live isolated instances were enumerated for desktop shell exit.",
    fields: { instanceCount: instanceIds.length, instanceIds: instanceIds.join(",").slice(0, 500) }
  });

  const outcomes = await Promise.allSettled(instanceIds.map(async (instanceId) => {
    const result = await withDesktopShellExitTimeout(
      (signal) => orchestrateBranchInstanceLifecycle("stop", {
        schemaVersion: 1,
        path: "desktop-shell-shutdown/branch-instances/stop",
        init: {
          method: "POST",
          body: { instanceId }
        }
      }, interruptActiveWork ? "operator-restart" : "operator", signal),
      deadline,
      `stop isolated instance ${instanceId}`
    );
    if (!result.accepted || result.code) {
      throw new Error(String(result.message || result.code || "isolated stop was not accepted"));
    }
    return result;
  }));

  for (let index = 0; index < outcomes.length; index += 1) {
    const instanceId = instanceIds[index];
    const outcome = outcomes[index];
    if (outcome.status === "fulfilled") {
      await recordDesktopExitEvent(deadline, {
        eventCode: "electron.isolated_instance.stopped",
        message: "Isolated instance stop completed during desktop shell exit.",
        fields: { instanceId }
      });
      continue;
    }
    const detail = outcome.reason instanceof Error ? outcome.reason.message : String(outcome.reason);
    await recordDesktopExitEvent(deadline, {
      eventCode: "electron.isolated_instance.stop_failed",
      message: "Isolated instance stop failed during desktop shell exit.",
      fields: { instanceId, error: detail.slice(0, 500) }
    });
  }
  const failedInstanceIds = outcomes.flatMap((outcome, index) =>
    outcome.status === "rejected" ? [instanceIds[index]] : []
  );
  if (failedInstanceIds.length > 0) {
    throw new Error(`Failed to stop isolated instances: ${failedInstanceIds.join(", ")}`);
  }
}

async function bestEffortStopIsolatedInstancesForShutdown(
  label: string,
  sharedDeadline?: DesktopShellExitDeadline
): Promise<void> {
  const ownsDeadline = sharedDeadline === undefined;
  const deadline = sharedDeadline ?? createDesktopShellExitDeadline();
  try {
    await withDesktopShellExitTimeout(
      () => stopIsolatedInstancesForApprovedShutdown(false, deadline),
      deadline,
      label
    );
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    await recordDesktopExitEvent(deadline, {
      eventCode: "electron.isolated_instances.stop_all_failed",
      message: "Isolated instance stop did not finish before the desktop shell exit step deadline.",
      fields: { error: detail.slice(0, 500), label: label.slice(0, 160) }
    });
  } finally {
    if (ownsDeadline) deadline.dispose();
  }
}

function localQuitActiveWorkStatus(): ActiveWorkStatus {
  try {
    const runs = listActiveWorkRuns(createDesktopPathsForApp().workspaceRoot);
    if (runs.length === 0) {
      return { state: "idle", message: "" };
    }
    return {
      state: "active",
      message: `${runs.length} active work item(s) block lifecycle commands.`,
      count: runs.length,
      items: runs.map((run) => ({ ...run }))
    };
  } catch (error: unknown) {
    return {
      state: "unknown",
      message: error instanceof Error ? error.message : String(error)
    };
  }
}

async function requestDesktopShellExit(
  closeReason: DesktopCloseReason = "desktop_shell_quit"
): Promise<ShutdownDecision> {
  return desktopLifecycleCoordinator.request(closeReason, async () => {
    const ownershipMode = launcherBootstrap?.mode ?? "attached";
    // Authorization, retry, stop and close all spend the same finite budget.
    const deadline = createDesktopShellExitDeadline(DESKTOP_QUIT_TOTAL_BUDGET_MS);
    try {
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
                const context = await withDesktopShellExitTimeout(
                  (signal) => resolveDesktopActionLoopContext(bootstrap, { forceControlTokenRefresh, signal }),
                  deadline,
                  "resolve quit control context"
                );
                return await withDesktopShellExitTimeout(
                  (signal) => fetchLauncherActiveWorkStatus({
                    ...context,
                    signal: AbortSignal.any([signal, deadline.signal])
                  }),
                  Math.max(1, Math.min(QUIT_ACTIVE_WORK_STATUS_TIMEOUT_MS, deadline.remainingMs())),
                  "resolve launcher active work status for quit"
                );
              };
              return await resolveQuitActiveWorkStatus({
                probe: () => probeQuitActiveWork(false),
                recoverAndRetry: () => probeQuitActiveWork(true)
              });
          },
          // The launcher probe rides on the workbench backend. When that backend
          // is dead or wedged the probe times out and quit used to fail with
          // "无法确认是否有进行中的任务" forever; the same file-based scan the
          // main-line stop command trusts keeps quit possible instead.
          localActiveWorkStatus: () => localQuitActiveWorkStatus()
        }),
        onDenied: (decision) => {
          notifyDesktopTray("Vibelution", decision.message || "有进行中的任务，暂时无法退出。可先用托盘“退出壳并停止全部任务”。", "warning");
        },
        runApproved: async (decision) => {
          pendingWorkbenchCloseAck = null;
          await withDesktopShellExitTimeout(async (signal) => {
            signal.throwIfAborted();
            const mainRuntimeAlreadyStopped = await joinWorkbenchCloseBackendStop(deadline);
            await stopIsolatedInstancesForApprovedShutdown(false, deadline);
            const shutdownResult = await executeApprovedDesktopShellShutdown({
              decision,
              closeDesktopSession: async (signal) => {
                signal.throwIfAborted();
                await closeDesktopSessionIfRegistered();
              },
              recordEvent: (event) => {
                recordSupervisorEventFallbackLocally({
                  ...event,
                  fields: {
                    closeReason,
                    ownershipMode,
                    ...(event.fields ?? {})
                  }
                });
              },
              stopManagedRuntime: mainRuntimeAlreadyStopped
                ? async () => undefined
                : (signal) => stopMainRuntimeForApprovedShutdown(false, signal),
              stopPythonLauncher: stopOwnedPythonLauncherService,
              approveShutdown: () => {
                shutdownApproved = true;
              },
              stopDesktopActionLoop,
              deadline,
              quitApp: () => {
                app.quit();
              }
            });
            if (shutdownResult?.managedRuntimeError || shutdownResult?.stopError) {
              notifyDesktopTray(
                "Vibelution",
                "运行时未能完整停止，已取消退出。请查看运行时状态后重试，或明确选择“退出壳并停止全部任务”。",
                "warning"
              );
            }
          }, deadline, "desktop shell exit");
        },
        onApprovedFailure: async (_decision, error) => {
          const message = error instanceof Error ? error.message : String(error);
          console.warn(message);
          recordSupervisorEventFallbackLocally({
            eventCode: "electron.desktop_shell.exit_blocked_stop_failed",
            message: "Desktop shell exit was cancelled because managed processes did not stop within budget.",
            fields: { closeReason, error: message.slice(0, 500), failOpen: false }
          });
          recordSupervisorEventFallbackLocally({
            eventCode: "electron.isolated_instances.stop_all_failed",
            message: "Isolated instance stop did not finish before the desktop shell exit budget.",
            fields: { closeReason, error: message.slice(0, 500), failOpen: false, retrySuppressed: true }
          });
          pendingWorkbenchCloseAck = null;
          notifyDesktopTray(
            "Vibelution",
            "运行时或隔离实例未能完整停止，已取消退出。可检查状态后重试，或明确选择“退出壳并停止全部任务”。",
            "warning"
          );
        }
      });
    } finally {
      deadline.dispose();
    }
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

async function resolveInterruptedActiveWork(): Promise<{ count: number; items: Record<string, unknown>[] }> {
  const bootstrap = launcherBootstrap;
  if (bootstrap === null) {
    return { count: 0, items: [] };
  }
  try {
    const status = await withDesktopShellExitTimeout(
      async (signal) => {
        const context = await resolveDesktopActionLoopContext(bootstrap, { signal });
        return await fetchLauncherActiveWorkStatus({ ...context, signal });
      },
      ACTIVE_WORK_STATUS_TIMEOUT_MS,
      "resolve launcher active work for tray force action"
    );
    return status.state === "active"
      ? { count: status.count ?? status.items?.length ?? 0, items: status.items ?? [] }
      : { count: 0, items: [] };
  } catch {
    return { count: 0, items: [] };
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
  await stopMainRuntimeForApprovedShutdown(true);
  await stopIsolatedInstancesForApprovedShutdown(true);
  await stopOwnedPythonLauncherService();
  const provider = windowProvider;
  if (provider !== null) {
    try {
      await provider.approveWorkbenchCloseOnce();
    } catch (error: unknown) {
      console.warn(error instanceof Error ? error.message : String(error));
    }
  }
}

async function restartLauncherToLatestBuild(
  interruptActiveWork = true,
  operationToRestore = "open",
  options: { shellKind?: "packaged" | "unpackaged"; forceRefresh?: boolean } = {}
): Promise<OrchestratedLifecycleResult> {
  if (shellRefreshInFlight) {
    return {
      schemaVersion: 1,
      accepted: false,
      operation: "restart-latest-shell",
      message: "桌面壳已经在更新，请稍候。"
    };
  }
  shellRefreshInFlight = true;
  try {
    const result = await executeLauncherUpdate({
      interruptActiveWork,
      activeWork: () => resolveLauncherUpdateActiveWork(true),
      prepare: () => ensureLatestLauncher({
        workspaceRoot: createDesktopPathsForApp().workspaceRoot,
        pythonPath: desktopPythonPath()
      }),
      stopWorkspaces: async () => {
        // Each task owner must confirm saved state before replacement.
        await stopMainRuntimeForApprovedShutdown(interruptActiveWork);
        await stopIsolatedInstancesForApprovedShutdown(interruptActiveWork);
      },
      scheduleReplacement: () => scheduleCurrentDesktopShellRefresh(operationToRestore, {
        // Only an explicit operator update may bypass the refresh cooldown.
        // Automatic freshness refreshes keep force off, so a repeatedly
        // failing rebuild cannot keep clearing its own cooldown and
        // re-stopping the workspace.
        force: options.forceRefresh !== false,
        // Callers that need a real promotion (rebuild-and-start) force the
        // packaged helper path; everyone else keeps the current shell kind.
        shellKind: options.shellKind ?? (app.isPackaged ? "packaged" : "unpackaged")
      })
    });
    if (!result.accepted) {
      shellRefreshInFlight = false;
      return result;
    }
    shutdownApproved = true;
    setTimeout(() => { void exitDesktopShellProcess().catch(() => console.warn("ASSISTANT_STOP_FAILED")); }, 250);
    return result;
  } catch (error: unknown) {
    shellRefreshInFlight = false;
    throw error;
  }
}

async function resolveLauncherUpdateActiveWork(refreshBranches = false): Promise<ActiveWorkStatus> {
  try {
    if (refreshBranches) await launcherStateStore.refresh("launcher_update_guard");
    const payload = await orchestrateLauncherApi("status", { schemaVersion: 1, path: "status" });
    const main = activeWorkStatusFromLauncherStatus(
      typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {}
    );
    if (main.state === "unknown") return main;
    const slots = parseBranchInstanceRecords(launcherStateStore.projectBranchInstances())
      .filter((item) => !item.current && item.path && item.alive);
    const isolated = slots.flatMap((slot) => listActiveWorkRuns(slot.path));
    const count = (main.count ?? 0) + isolated.length;
    return { state: count ? "active" : "idle", message: "", count, items: [...(main.items ?? []), ...isolated].slice(0, 8) };
  } catch {
    return { state: "unknown", message: "Launcher task status is unavailable." };
  }
}

async function currentLauncherUpdateFreshness(): Promise<Record<string, unknown>> {
  const [rawResult, shellResult, activeWorkResult] = await Promise.allSettled([
    orchestrateLauncherApi("freshness", { schemaVersion: 1, path: "freshness" }),
    app.isPackaged ? inspectCurrentDesktopShell() : Promise.resolve(undefined),
    resolveLauncherUpdateActiveWork()
  ]);
  if (app.isPackaged) {
    const inspected = shellResult.status === "fulfilled" ? shellResult.value : undefined;
    lastKnownDesktopShell = retainKnownDesktopShell(lastKnownDesktopShell, inspected);
  }
  if (rawResult.status !== "fulfilled") {
    throw rawResult.reason;
  }
  const activeWork = activeWorkResult.status === "fulfilled"
    ? activeWorkResult.value
    : { state: "unknown" as const, message: "Launcher task status is unavailable." };
  return projectLauncherUpdateFreshness({
    raw: rawResult.value,
    shell: app.isPackaged ? lastKnownDesktopShell : undefined,
    activeWork,
    packaged: app.isPackaged,
    updating: shellRefreshInFlight
  });
}

async function exitAndRelaunchLauncherShell(options: { forceShellRefresh?: boolean } = {}): Promise<void> {
  const forceRefresh = options.forceShellRefresh === true;
  let launchBlocking = false;
  if (app.isPackaged) {
    try {
      launchBlocking = (await inspectCurrentDesktopShell()).launchBlocking;
    } catch {
      launchBlocking = false;
    }
  }
  const decision = decideLauncherShellRestart({
    isPackaged: app.isPackaged,
    launchBlocking,
    forceRefresh
  });
  if (decision === "rebuild-and-exit") {
    shellRefreshInFlight = true;
    try {
      // The replacement shell must restore the workbench, not only the tray:
      // carry the start lifecycle so the new shell brings the backend up.
      await scheduleCurrentDesktopShellRefresh("start", { force: forceRefresh });
    } catch (error: unknown) {
      shellRefreshInFlight = false;
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法安排桌面壳更新，继续使用当前壳重启：${detail.slice(0, 220)}`, "warning");
      app.relaunch();
      shutdownApproved = true;
      await exitDesktopShellProcess();
      return;
    }
    shutdownApproved = true;
    await exitDesktopShellProcess();
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
      // Preparation never replaces a loaded native addon. The same refresh
      // helper as the update button waits for this Electron owner to exit.
      shellRefreshInFlight = true;
      await scheduleCurrentDesktopShellRefresh("start", { force: true, shellKind: "unpackaged" });
      shutdownApproved = true;
      await exitDesktopShellProcess();
      return;
    } catch (error: unknown) {
      shellRefreshInFlight = false;
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `无法重建最新前端，仍将重启当前壳：${detail.slice(0, 220)}`, "warning");
    }
  }
  app.relaunch();
  shutdownApproved = true;
  await exitDesktopShellProcess();
}

async function runTrayRestartLauncher(): Promise<void> {
  if (trayRestartLauncherInFlight || trayRestartAllInFlight || trayQuitAllInFlight || shellRefreshInFlight) {
    notifyDesktopTray("Vibelution", "已有托盘操作进行中，请稍候。", "warning");
    return;
  }
  trayRestartLauncherInFlight = true;
  const paths = createDesktopPathsForApp();
  try {
    const interruptedActiveWork = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
      ? await resolveInterruptedActiveWork()
      : { count: 0, items: [] };
    const interruptedActiveWorkCount = interruptedActiveWork.count;
    if (interruptedActiveWorkCount > 0) {
      await recordTrayForceInterruptEvidence("electron.tray.restart_launcher.force_interrupt", "Tray restart-launcher proceeding while active work was present.", {
        interruptedActiveWorkCount,
        interruptedActiveWorkItems: JSON.stringify(interruptedActiveWork.items)
      });
    }
    clearTrayRestartAllPending(paths.workspaceRoot);
    notifyDesktopTray("Vibelution", "正在全部停止并启动最新 Launcher…");
    await stopAllManagedRuntimeTrees();
    await exitAndRelaunchLauncherShell({ forceShellRefresh: true });
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    if (isForceLifecycleAuthorizationDenied(error)) {
      notifyDesktopTray("Vibelution", "已取消全部停止，当前窗口、运行时和任务均保留。", "info");
      return;
    }
    notifyDesktopTray("Vibelution", `全部停止并启动最新 Launcher 失败：${detail.slice(0, 220)}`, "warning");
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
    const interruptedActiveWork = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
      ? await resolveInterruptedActiveWork()
      : { count: 0, items: [] };
    const interruptedActiveWorkCount = interruptedActiveWork.count;
    if (interruptedActiveWorkCount > 0) {
      await recordTrayForceInterruptEvidence("electron.tray.restart_all.force_interrupt", "Tray restart-all proceeding while active work was present.", {
        interruptedActiveWorkCount,
        interruptedActiveWorkItems: JSON.stringify(interruptedActiveWork.items)
      });
    }
    let runningInstanceIds: string[] = [];
    try {
      const refreshed = await launcherStateStore.refresh("tray_restart_all_capture");
      runningInstanceIds = captureRunningInstanceIds(
        await fetchLauncherBranchInstances({
          ...(await resolveTrayControlContextOrLoopback()),
          requestTimeoutMs: 20_000
        })
      );
      runningInstanceIds = Array.from(new Set([
        ...runningInstanceIds,
        ...captureShutdownInstanceIds(refreshed.instances)
      ]));
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
    try {
      await stopAllManagedRuntimeTrees();
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      clearTrayRestartAllPending(paths.workspaceRoot);
      if (isForceLifecycleAuthorizationDenied(error)) {
        notifyDesktopTray("Vibelution", "已取消全部重启，当前窗口、运行时和任务均保留。", "info");
      } else {
        notifyDesktopTray("Vibelution", `全部重启未完成：${detail.slice(0, 220)}`, "warning");
      }
      return;
    }
    if (app.isPackaged && stale) {
      shellRefreshInFlight = true;
      writeTrayRestartAllPending(paths.workspaceRoot, {
        instanceIds: runningInstanceIds,
        interruptedActiveWorkCount,
        shellRefreshScheduled: true
      });
      try {
        await scheduleCurrentDesktopShellRefresh("start", { force: true });
      } catch (error: unknown) {
        shellRefreshInFlight = false;
        const detail = error instanceof Error ? error.message : String(error);
        notifyDesktopTray("Vibelution", `无法安排桌面壳更新：${detail.slice(0, 220)}`, "warning");
        clearTrayRestartAllPending(paths.workspaceRoot);
        return;
      }
      shutdownApproved = true;
      await exitDesktopShellProcess();
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
      const interruptedActiveWork = ACTIVE_WORK_POLICY_FORCE_INTERRUPT
        ? await resolveInterruptedActiveWork()
        : { count: 0, items: [] };
      const interruptedActiveWorkCount = interruptedActiveWork.count;
      if (interruptedActiveWorkCount > 0) {
        await recordTrayForceInterruptEvidence("electron.tray.quit_all.force_interrupt", "Tray quit-all proceeding while active work was present.", {
          interruptedActiveWorkCount,
          interruptedActiveWorkItems: JSON.stringify(interruptedActiveWork.items)
        });
      }
      const deadline = createDesktopShellExitDeadline();
      let mainRuntimeAlreadyStopped = false;
      try {
        mainRuntimeAlreadyStopped = await joinWorkbenchCloseBackendStop(deadline);
        if (!mainRuntimeAlreadyStopped) {
          await withDesktopShellExitTimeout(
            (signal) => orchestrateLauncherLifecycle("force-stop", { schemaVersion: 1, path: "force-stop" }, "operator", signal),
            deadline,
            "force stop main runtime"
          );
          await withDesktopShellExitTimeout(
            (signal) => delayWithAbortSignal(1_500, signal),
            deadline,
            "wait for forced runtime stop"
          );
        }
      } catch (error: unknown) {
        if (isForceLifecycleAuthorizationDenied(error)) {
          notifyDesktopTray("Vibelution", "已取消退出，当前窗口、运行时和任务均保留。", "info");
          deadline.dispose();
          return;
        }
        if (shouldNotifyForceStopControlFailure(error)) {
          const detail = error instanceof Error ? error.message : String(error);
          notifyDesktopTray("Vibelution", `停止托管运行时失败：${detail.slice(0, 220)}`, "warning");
        }
      }
      pendingWorkbenchCloseAck = null;
      try {
        await withDesktopShellExitTimeout(async (signal) => {
          signal.throwIfAborted();
          await bestEffortStopIsolatedInstancesForShutdown(
            "stop isolated instances before forced desktop shell exit",
            deadline
          );
          await executeApprovedDesktopShellShutdown({
            decision: { allowed: true, reason: "no_active_work", stopPythonLauncher: true },
            closeDesktopSession: async (signal) => {
              signal.throwIfAborted();
              await closeDesktopSessionIfRegistered();
            },
            recordEvent: (event) => {
              recordSupervisorEventFallbackLocally({
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
            stopManagedRuntime: mainRuntimeAlreadyStopped ? async () => undefined : stopManagedRuntime,
            stopPythonLauncher: stopOwnedPythonLauncherService,
            approveShutdown: () => {
              shutdownApproved = true;
            },
            stopDesktopActionLoop,
            deadline,
            quitApp: () => {
              app.quit();
            },
            forceExitOnStopFailure: true
          });
        }, deadline, "forced desktop shell exit");
      } finally {
        deadline.dispose();
      }
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

/**
 * Observe already-open workbench windows for backend liveness. The window-open
 * gate only protects the moment a window is created; once a backend dies under
 * an open window nothing else reloads it onto a recovered backend, which is
 * exactly the frozen-window incident this loop closes. Pure observation plus
 * window reload — it never touches backend processes or the lifecycle
 * coordinator, and only loopback HTTP(S) workbench origins are ever probed.
 */
function startWorkbenchBackendWatchdogLoop(): void {
  if (workbenchBackendWatchdog !== null) {
    return;
  }
  workbenchBackendWatchdog = startWorkbenchBackendWatchdog({
    listWindows: () =>
      BrowserWindow.getAllWindows().map((window) => ({
        id: window.id,
        getUrl: () => window.webContents.getURL(),
        isDestroyed: () => window.isDestroyed(),
        reload: () => window.webContents.reload(),
        getTitle: () => window.getTitle(),
        setTitle: (title: string) => window.setTitle(title)
      })),
    log: (event) => {
      if (event.kind === "tick-error") {
        console.warn(event.message);
        return;
      }
      void recordElectronSupervisorEvent(launcherBootstrap, {
        eventCode:
          event.kind === "origin-degraded"
            ? "electron.workbench_backend_watchdog.degraded"
            : "electron.workbench_backend_watchdog.recovered",
        message:
          event.kind === "origin-degraded"
            ? "Workbench backend origin stopped answering; windows marked offline."
            : "Workbench backend origin answered again; matching windows reloaded.",
        fields: { origin: event.origin }
      });
    }
  });
}

function stopWorkbenchBackendWatchdogLoop(): void {
  workbenchBackendWatchdog?.dispose();
  workbenchBackendWatchdog = null;
}

function startPeriodicShellFreshnessWatch(): void {
  if (periodicShellFreshnessTimer !== null) {
    return;
  }
  periodicShellFreshnessTimer = setInterval(() => {
    void (async () => {
      if (
        !shouldProbePeriodicDesktopShell({
          isPackaged: app.isPackaged,
          smoke: desktopCliArgs.smoke,
          workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
          refreshInFlight: shellRefreshInFlight || trayRestartAllInFlight || trayQuitAllInFlight || trayRestartLauncherInFlight,
          shutdownApproved
        })
      ) {
        return;
      }
      let status: DesktopShellStatus | null = null;
      try {
        status = await inspectCurrentDesktopShell();
      } catch {
        return;
      }
      if (!status.stale) {
        periodicAdvisoryStaleNotified = false;
      }
      const decision = decidePeriodicDesktopShellRefresh({
        isPackaged: app.isPackaged,
        smoke: desktopCliArgs.smoke,
        workbenchCloseCanary: desktopCliArgs.workbenchCloseCanary,
        stale: status.stale,
        launchBlocking: status.launchBlocking,
        refreshInFlight: shellRefreshInFlight || trayRestartAllInFlight || trayQuitAllInFlight || trayRestartLauncherInFlight,
        shutdownApproved,
        refreshBlocked: status.refreshBlocked
      });
      if (decision === "advisory") {
        // Advisory staleness keeps serving windows from a usable frontend
        // release; a periodic probe must never stop the workspace for it.
        if (!periodicAdvisoryStaleNotified) {
          periodicAdvisoryStaleNotified = true;
          console.warn(
            `periodic shell probe: advisory staleness (${status.reason || "unknown"}); automatic shell replacement stays disabled`
          );
          notifyDesktopTray(
            "Vibelution",
            "桌面壳落后但当前窗口仍可用，已跳过自动更换；可在启动器面板手动更新。",
            "info"
          );
        }
        return;
      }
      if (decision !== "refresh") {
        return;
      }
      await refreshPackagedDesktopShellIfStale("start");
    })().catch((error: unknown) => {
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
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  return app.getVersion();
});

ipcMain.handle(IPC_CHANNELS.getDesktopShellSummary, (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  return {
    schemaVersion: 1,
    provider: "electron",
    currentWindow: identifyDebugWindow(event.sender.getOSProcessId(), windowProvider?.snapshot() ?? null, windowProvider?.instanceWindowStates() ?? []),
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

const controlPetFromSettings = createPetSettingsControl(() => windowProvider);
ipcMain.handle(IPC_CHANNELS.controlDesktopPet, async (event, open: unknown, mode: unknown) => {
  const instances = windowProvider?.instanceWindowStates() ?? [];
  assertTrustedIpcSender(event, [...trustedIpcOrigins(), ...instances.filter(item => item.open).map(item => new URL(item.url).origin)]);
  if (event.senderFrame !== event.sender.mainFrame) throw new Error("Blocked pet settings subframe");
  const identity = identifyDebugWindow(event.sender.getOSProcessId(), windowProvider?.snapshot() ?? null, instances);
  const origin = petSettingsOrigin(event.senderFrame.url, identity.role);
  return controlPetFromSettings(origin, open, mode);
});

ipcMain.handle(IPC_CHANNELS.openConversationFromPet, async (event, rawSessionId: unknown) => {
  assertDesktopPetIpcSender(event);
  const fromDesktopAssistant = new URL(String(event.senderFrame?.url)).pathname === "/desktop-assistant";
  const sessionId = String(rawSessionId || "").trim();
  if (!/^[A-Za-z0-9._:-]{1,128}$/.test(sessionId)) {
    throw new Error("invalid desktop pet session id");
  }
  const provider = windowProvider;
  if (provider === null) {
    return { schemaVersion: 1, opened: false };
  }
  if (fromDesktopAssistant) {
    const pet = provider.snapshot().pet;
    if (!pet.open || new URL(pet.url).pathname !== "/desktop-assistant") {
      return { schemaVersion: 1, opened: false };
    }
    const delivered = provider.focusAndSendToWorkbenchOrigin(new URL(pet.url).origin, IPC_CHANNELS.conversationNotificationOpened, {
      schemaVersion: 1,
      sessionId,
      source: "desktop-assistant",
    });
    return { schemaVersion: 1, opened: delivered };
  }
  let state = await provider.focusWorkbench();
  if (!state.open) {
    const url = currentWorkbenchUrl || launcherBootstrap?.workbenchUrl;
    if (!url) {
      return { schemaVersion: 1, opened: false };
    }
    state = await provider.openOrFocusWorkbench(url);
  }
  const delivered = provider.sendToWorkbench(IPC_CHANNELS.conversationNotificationOpened, {
    schemaVersion: 1,
    sessionId,
  });
  return { schemaVersion: 1, opened: state.open && delivered };
});

let activeDesktopPetWindowDrag: { senderId: number; drag: DesktopPetWindowDrag } | null = null;

function assertDesktopPetIpcSender(event: IpcMainInvokeEvent | IpcMainEvent): void {
  const pet = windowProvider?.snapshot().pet;
  const origins = pet?.open ? [...trustedIpcOrigins(), new URL(pet.url).origin] : trustedIpcOrigins();
  assertTrustedIpcSender(event as IpcMainInvokeEvent, origins);
  const rawUrl = String(event.senderFrame?.url || "");
  const identity = identifyDebugWindow(event.sender.getOSProcessId(), windowProvider?.snapshot() ?? null, windowProvider?.instanceWindowStates() ?? []);
  if (event.senderFrame !== event.sender.mainFrame || identity.role !== "desktop-pet" || !isDesktopPetWindowUrl(rawUrl)) {
    throw new Error("blocked desktop pet ipc sender");
  }
}

ipcMain.handle(IPC_CHANNELS.getDesktopAssistantContext, (event) => {
  assertDesktopPetIpcSender(event);
  if (new URL(String(event.senderFrame?.url)).pathname !== "/desktop-assistant") {
    throw new Error("blocked desktop assistant context sender");
  }
  return { role: "desktop-assistant", mode: "assistant" };
});

ipcMain.handle(IPC_CHANNELS.setDesktopPetExpanded, (event, expanded: unknown) => {
  assertDesktopPetIpcSender(event);
  if (typeof expanded !== "boolean") throw new Error("Invalid desktop pet expanded state");
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window || window.isDestroyed()) throw new Error("Desktop pet window is not available");
  const current = window.getBounds();
  const bounds = desktopPetWindowExpandedBounds(current, screen.getDisplayMatching(current).workArea, expanded);
  activeDesktopPetWindowDrag = null;
  window.setBounds(bounds, false);
  return { expanded, width: bounds.width, height: bounds.height };
});

function desktopPetWindowFromEvent(event: IpcMainEvent): BrowserWindow | null {
  try {
    assertDesktopPetIpcSender(event);
  } catch {
    return null;
  }
  const window = BrowserWindow.fromWebContents(event.sender);
  return window && !window.isDestroyed() ? window : null;
}

ipcMain.on(IPC_CHANNELS.beginDesktopPetWindowDrag, (event, rawPoint: unknown) => {
  const window = desktopPetWindowFromEvent(event);
  if (window === null || !isDesktopPetDragPoint(rawPoint)) {
    return;
  }
  const { x, y, width, height } = window.getBounds();
  activeDesktopPetWindowDrag = {
    senderId: event.sender.id,
    drag: beginDesktopPetWindowDrag(rawPoint, {
      x,
      y,
      width,
      height,
    }),
  };
});

ipcMain.on(IPC_CHANNELS.moveDesktopPetWindowDrag, (event, rawPoint: unknown) => {
  const window = desktopPetWindowFromEvent(event);
  const active = activeDesktopPetWindowDrag;
  if (window === null || active === null || active.senderId !== event.sender.id || !isDesktopPetDragPoint(rawPoint)) {
    return;
  }
  window.setBounds(desktopPetWindowBoundsAt(active.drag, rawPoint), false);
});

ipcMain.on(IPC_CHANNELS.endDesktopPetWindowDrag, (event) => {
  if (activeDesktopPetWindowDrag?.senderId === event.sender.id) {
    activeDesktopPetWindowDrag = null;
  }
});

ipcMain.handle(IPC_CHANNELS.requestDesktopShellExit, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return await requestDesktopShellExit();
});

ipcMain.handle(IPC_CHANNELS.notifyConversationCompleted, async (event, payload: DesktopConversationCompletionNotification) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  const service = resolveConversationNotificationService(event);
  if (service === null) {
    return failedConversationNotificationResult(payload);
  }
  return await service.notify(payload);
});

ipcMain.handle(IPC_CHANNELS.notifyHumanAttention, async (event, payload: unknown) => {
  return await handleHumanAttentionIpc(event, payload, windowProvider, trustedIpcOrigins(event),
    (acceptedPayload, source) => resolveHumanAttentionNotificationService().notify(acceptedPayload, source),
    legacyReminderAdmission ?? undefined);
});

ipcMain.handle(IPC_CHANNELS.humanAttentionCapabilities, async (event) => {
  // Until a source has a verified main-owned sender, retain existing delivery.
  return await handleHumanAttentionCapabilityIpc(event, windowProvider, trustedIpcOrigins(event));
});

ipcMain.handle(IPC_CHANNELS.openExternalUrl, async (event, rawUrl: unknown) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  if (!isExternalOpenableUrl(rawUrl)) {
    return false;
  }
  try {
    await shell.openExternal(rawUrl);
    return true;
  } catch {
    return false;
  }
});

ipcMain.handle(IPC_CHANNELS.openPath, async (event, rawPath: unknown) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  const target = normalizeAbsoluteOpenPath(rawPath);
  if (target === null) {
    return "";
  }
  return await shell.openPath(target);
});

ipcMain.handle(IPC_CHANNELS.showItemInFolder, (event, rawPath: unknown) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  const target = normalizeAbsoluteOpenPath(rawPath);
  if (target === null) {
    return false;
  }
  shell.showItemInFolder(target);
  return true;
});

function launcherIpcTrustedOrigins(): string[] {
  const desktopEnv = desktopEnvironment();
  return [launcherAppOriginFor(resolveLauncherWindowUrl(desktopEnv))];
}

async function orchestrateLauncherLifecycle(
  operation: string,
  payload: LauncherIpcInvokePayload,
  provenance: LauncherLifecycleProvenance = "operator",
  signal?: AbortSignal,
  fastCloseTiming?: WorkbenchCloseTiming,
  nativeColdStart = false,
  lifecycleCurrent?: () => boolean
): Promise<OrchestratedLifecycleResult> {
  if (launcherBootstrap === null) {
    throw new Error("Launcher backend is not available.");
  }
  if (nativeColdStart && shutdownApproved) {
    throw new Error("Desktop shell is shutting down.");
  }
  if (lifecycleCurrent && !lifecycleCurrent()) return supersededLifecycleResult(operation);
  const forceAuthorization = await authorizeLauncherForceLifecycle({
    operation,
    instanceId: "main",
    payload,
    operatorIntent: payload.path || operation
  });
  signal?.throwIfAborted();
  const desktopEnv = desktopEnvironment();
  const pythonPath = String(desktopEnv.VIBELUTION_PYTHON_PATH || desktopEnv.PYTHON || "").trim();
  if (!pythonPath) {
    throw new Error("VIBELUTION_PYTHON_PATH or PYTHON is required to orchestrate the workbench lifecycle");
  }
  const supervisedOperation = normalizeSupervisedLifecycleOperation(operation);
  const desiredState = desiredStateForLifecycleOperation(supervisedOperation);
  const paths = createDesktopPathsForApp();
  const startsWorkbench = supervisedOperation === "start"
    || supervisedOperation === "restart"
    || supervisedOperation === "rebuild-and-start";
  const closeBlocksStart = (): boolean => workbenchFailedCloseHandling
    || isWorkbenchStartBlockedByClose(hasBackgroundWorkbenchRetirement(paths.workspaceRoot),
      mainWorkbenchCloseStore.currentTransaction(), pendingWorkbenchCloseAck !== null);
  if (startsWorkbench && closeBlocksStart()) {
    return { schemaVersion: 1, accepted: false, operation, code: "backend_retiring",
      message: "后台进程仍在回收，请等待 Launcher 确认停止。" };
  }
  let frontendReleaseChanged = false;
  let frontendCheckedForReuse = false;
  let shellStale = false;

  // A positive no-dispatch response must precede even beginIntent: that call
  // can supersede an in-flight command. Current cold starts can reuse this
  // read-only gate below; warm reuse/refresh keep the full legacy entry path.
  let nativeReadiness: DesktopShellLaunchReadiness | null = null;
  if (nativeColdStart) {
    const admissionGeneration = launcherLifecycleSupervisor.intentGeneration("main");
    if (supervisedOperation !== "start") throw new Error("Native transport only supports start.");
    if (app.isPackaged && !await mainLineBackendIsReachable(paths.workspaceRoot)) {
      nativeReadiness = await inspectCurrentDesktopShellLaunchReadiness(signal);
    }
    if (shutdownApproved) throw new Error("Desktop shell is shutting down.");
    if (admissionGeneration !== launcherLifecycleSupervisor.intentGeneration("main")) {
      return supersededLifecycleResult(operation);
    }
    if (nativeReadiness === null || nativeReadiness.launchBlocking) {
      return { schemaVersion: 1, accepted: false, operation, code: "native_requires_legacy_launch" };
    }
  }

  // Claim cancellation before frontend preflight: a close must also supersede
  // a build that has not reached the serialized backend mutation yet.
  let lifecycleOperation: WorkbenchLifecycleOperation = operation as WorkbenchLifecycleOperation;
  const stopJoinDecision = joinDecisionForLauncherLifecycleStop(operation, provenance);
  if (stopJoinDecision.waitForInFlightRestart) {
    await waitForInFlightRestartSettlement("main", WORKBENCH_CLOSE_RESTART_JOIN_WAIT_MS, signal);
  }
  signal?.throwIfAborted();
  if (lifecycleCurrent && !lifecycleCurrent()) return supersededLifecycleResult(operation);
  // A close can be admitted while the native readiness check is awaiting I/O.
  // Recheck immediately before acquiring the intent that could supersede it.
  if (startsWorkbench && closeBlocksStart()) {
    return { schemaVersion: 1, accepted: false, operation, code: "backend_retiring",
      message: "后台进程仍在回收，请等待 Launcher 确认停止。" };
  }
  const begunIntent = launcherLifecycleSupervisor.beginIntentWithOptions(
    { instanceId: "main", operation: lifecycleOperation, desiredState },
    { joinInFlightRestart: stopJoinDecision.joinInFlightRestart }
  );
  if (begunIntent.outcome === "joined-in-flight-restart") {
    return {
      schemaVersion: 1, accepted: true, operation, commandId: randomUUID(),
      code: "joined_in_flight_restart",
      message: "在途 Launcher restart/rebuild-and-start 正在执行；本次转发的 stop 未中断它。"
    };
  }
  const intentLease = begunIntent.lease;
  if (startsWorkbench) launcherStateStore.beginMainLifecycle(supervisedOperation);
  const lifecycleSignal = signal
    ? AbortSignal.any([signal, intentLease.signal])
    : intentLease.signal;

  try {
    if (startsWorkbench) {
      // A live backend can bypass the mutation, so verify its release here.
      // Cold starts and restarts verify inside the queued mutation instead,
      // keeping one full fingerprint scan at the actual startup boundary.
      if (supervisedOperation === "start" && windowProvider !== null
        && await mainLineBackendIsReachable(paths.workspaceRoot)) {
        const frontend = await runWithFrontendBuildGate(
          "main",
          { operation: supervisedOperation, notify: () => updateLauncherWindowTruth() },
          () => ensureFrontendRelease({
            workspaceRoot: paths.workspaceRoot,
            pythonPath,
            signal: lifecycleSignal
          })
        );
        frontendReleaseChanged = !frontend.skipped;
        frontendCheckedForReuse = true;
      }
      lifecycleSignal.throwIfAborted();
      if (!app.isPackaged) {
        try {
          const shell = await inspectUnpackagedShell({
            workspaceRoot: paths.workspaceRoot,
            pythonPath,
            signal: lifecycleSignal
          });
          shellStale = shell.stale && shell.reason !== "missing_binary";
        } catch (error: unknown) {
          console.warn(error instanceof Error ? error.message : String(error));
        }
      }
    }

    lifecycleSignal.throwIfAborted();
  } catch (error: unknown) {
    launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
    throw error;
  }
  if (supervisedOperation === "start" && windowProvider !== null) {
    // Advisory packaged staleness (the sealed frontend hash differs, but the
    // shell is still usable) must not turn "open the workbench" into a restart.
    // That restart is not an explicit user restart, so active work only queues
    // it and the click looks dead. A launch-blocking shell still skips reuse
    // and falls through to the existing refresh gate.
    let packagedShellBlocksReuse = false;
    let packagedShellAdvisoryStale = false;
    // This probe only decides whether an already verified live backend can
    // bypass the mutation. Otherwise the final shell gate below is sufficient;
    // each full shell inspection also scans the frontend build inputs.
    if (app.isPackaged && frontendCheckedForReuse && !frontendReleaseChanged) {
      try {
        const status = await inspectCurrentDesktopShell();
        packagedShellBlocksReuse = Boolean(status.launchBlocking);
        packagedShellAdvisoryStale = Boolean(status.stale) && !packagedShellBlocksReuse;
      } catch (error: unknown) {
        if (nativeColdStart) {
          launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
          throw error;
        }
        console.warn(error instanceof Error ? error.message : String(error));
        packagedShellBlocksReuse = await packagedDesktopShellIsStale();
      }
    }
    let servingVersion = { ok: false, reason: "release_or_shell_changed" };
    try {
      if (frontendCheckedForReuse && !frontendReleaseChanged && !packagedShellBlocksReuse) {
        servingVersion = await inspectWorkbenchServingVersion({ workspaceRoot: paths.workspaceRoot, readiness: "shell", signal: lifecycleSignal });
      }
      lifecycleSignal.throwIfAborted();
    } catch (error: unknown) {
      launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
      throw error;
    }
    if (!servingVersion.ok && servingVersion.reason !== "release_or_shell_changed") {
      console.warn(`main-line backend reuse rejected: ${servingVersion.reason}`);
    }
    if (
      frontendCheckedForReuse
      && !frontendReleaseChanged
      && !packagedShellBlocksReuse
      && servingVersion.ok
      && await mainLineBackendIsReusable(paths.workspaceRoot)
    ) {
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      const url = await refreshLiveWorkbenchUrl(paths);
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      await openWorkbenchAtCurrentLauncherUrl(paths, launcherBootstrap, windowProvider, { workbenchUrl: url });
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      scheduleLauncherStatusCliRefresh();
      const reportShellStale = shellStale || packagedShellAdvisoryStale;
      return {
        schemaVersion: 1,
        accepted: true,
        operation,
        // Even a reused backend needs a correlation id: Launcher IPC clients use
        // it to settle the open command and the lifecycle supervisor uses the
        // same shape for every accepted main-line result.
        commandId: randomUUID(),
        ...(forceAuthorization ? { requestId: forceAuthorization.requestId } : {}),
        ...(reportShellStale ? { shellStale: true } : {}),
        message: workbenchOpenedMessage(reportShellStale)
      };
    }
    // A reachable but non-reusable backend may be serving an older immutable
    // release.  Route it through restart instead of the destructive start path
    // so the active-work guard can preserve an in-progress formal task.
    if (await mainLineBackendIsReachable(paths.workspaceRoot)) {
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      lifecycleOperation = "restart";
    }
  }
  // The refresh gate is no longer packaged-only: rebuild-and-start keeps its
  // promotion promise on an unpackaged running shell too, while packaged
  // start/restart/rebuild-and-start still require a launch-blocking shell.
  let refreshBeforeLifecycle = shouldRefreshBeforeLifecycle(lifecycleOperation, {
    isPackaged: app.isPackaged,
    launchBlocking: false
  });
  if (shouldInspectDesktopShellBeforeLifecycle(lifecycleOperation, app.isPackaged)) {
    try {
      const status = nativeReadiness && !frontendCheckedForReuse && lifecycleOperation === "start"
        ? nativeReadiness : await inspectCurrentDesktopShellLaunchReadiness(lifecycleSignal);
      if (!launcherLifecycleSupervisor.isCurrent(intentLease)) {
        return supersededLifecycleResult(operation);
      }
      refreshBeforeLifecycle = shouldRefreshBeforeLifecycle(lifecycleOperation, { isPackaged: true, launchBlocking: status.launchBlocking });
    } catch (error: unknown) {
      if (nativeColdStart) {
        launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
        throw error;
      }
      console.warn(error instanceof Error ? error.message : String(error));
    }
  }
  if (refreshBeforeLifecycle) {
    notifyDesktopTray("Vibelution", "桌面壳不是当前代码，Launcher 正在更新后再执行…");
    try {
      return await restartLauncherToLatestBuild(
        operation === "restart" && provenance === "operator",
        lifecycleOperation,
        // The helper must promote and relaunch the packaged shell even when
        // the current running shell is unpackaged.
        { shellKind: "packaged" }
      );
    } finally {
      launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
    }
  }
  // Snapshot the pre-mutation backend identity so the post-start verification
  // can prove the lifecycle operation actually replaced the serving process
  // (2026-09-11: a "restarted" workbench kept serving a two-day-old build).
  const preMutationBackendState = readLauncherStateFile(launcherStatePath(paths.workspaceRoot));
  const preMutationBackendIdentity: ServingProcessIdentity | null = Number(preMutationBackendState.backendPid || 0) > 0
    ? {
      pid: Number(preMutationBackendState.backendPid),
      createTime: Number(preMutationBackendState.backendCreateTime || 0)
    }
    : null;
  const mutation = await launcherLifecycleSupervisor.executeMutation({
    lease: intentLease,
    mutate: async () => await runWorkbenchLifecycle({
      workspaceRoot: paths.workspaceRoot,
      pythonPath,
      operatorConfigPath:
        launcherBootstrap?.operatorConfigPath || String(desktopEnv.VIBELUTION_CONFIG_PATH || "").trim(),
      operation: lifecycleOperation,
      interruptActiveWork: provenance === "operator-restart" || (operation === "restart" && provenance === "operator"),
      ...(fastCloseTiming && preconfirmedCloseAuthorization("main", payload)
        ? { fastCloseTiming, controlToken: desktopActionContext?.controlToken } : {}),
      // Never cache the earlier reuse probe: queueing can overlap source
      // changes, and a rejected reuse must revalidate before spawning.
      ensureFrontend: async ({ signal: buildSignal }) => {
        await runWithFrontendBuildGate(
          "main",
          { operation: supervisedOperation, notify: () => updateLauncherWindowTruth() },
          () => ensureFrontendRelease({ workspaceRoot: paths.workspaceRoot, pythonPath, signal: buildSignal })
        );
      },
      signal: lifecycleSignal
    }),
    reconcile: async () => {
      scheduleLauncherStatusCliRefresh();
    }
  });
  if (mutation.outcome === "failed") {
    // A permanently failed intent must not keep occupying the instance slot in
    // intent phase, or a later join-eligible stop would keep joining a
    // restart that can never finish.
    launcherLifecycleSupervisor.clearSlotIfCurrent(intentLease);
    throw mutation.error;
  }
  if (mutation.outcome === "uncertain") {
    throw new Error(`Launcher lifecycle ${operation} outcome is uncertain; reconciliation started.`);
  }
  if (mutation.outcome === "ignored") {
    return supersededLifecycleResult(operation);
  }
  // Keep the accepted-result contract total at the Electron boundary. The
  // normal queue path supplies commandId, but a legacy/short-circuit bridge
  // result must not prevent the window orchestration gates from running.
  const result = mutation.value.accepted && !mutation.value.commandId?.trim()
    ? { ...mutation.value, commandId: randomUUID() }
    : mutation.value;
  if (mutation.outcome === "superseded") {
    return supersededLifecycleResult(operation, result.commandId);
  }
  const lease = result.accepted && result.commandId
    ? launcherLifecycleSupervisor.bindCommand(intentLease, { commandId: result.commandId })
    : intentLease;
  if (lease === null || !launcherLifecycleSupervisor.isCurrent(lease)) {
    return supersededLifecycleResult(operation, result.commandId);
  }
  if (
    result.accepted
    && (lifecycleOperation === "start" || lifecycleOperation === "restart" || lifecycleOperation === "rebuild-and-start")
  ) {
    const provider = windowProvider;
    if (provider !== null && result.commandId) {
      const readyWaitMs = lifecycleOperation === "rebuild-and-start"
        ? WORKBENCH_REBUILD_READY_WAIT_MS
        : WORKBENCH_START_READY_WAIT_MS;
      void openWorkbenchAfterLifecycleReady(
        paths,
        launcherBootstrap,
        provider,
        lease,
        readyWaitMs,
        preMutationBackendIdentity
      ).catch((error: unknown) => {
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
  const shellNote = shellStale && result.accepted ? SHELL_STALE_NOTE : "";
  return {
    ...result,
    ...(shellStale && result.accepted ? { shellStale: true } : {}),
    ...(shellNote
      ? { message: result.message ? `${result.message} ${shellNote}` : shellNote }
      : {}),
    ...(forceAuthorization ? { requestId: forceAuthorization.requestId } : {})
  };
}

const SHELL_STALE_NOTE = "桌面壳仍是旧版本，刷新桌面壳后才会换上桌面代码。";

function workbenchOpenedMessage(shellStale: boolean): string {
  return shellStale ? `已打开工作台窗口。${SHELL_STALE_NOTE}` : "已打开工作台窗口。";
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
  if (transaction === null || !["backend_closing", "background_closing"].includes(transaction.phase)) {
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

/**
 * Where a lifecycle command came from. Operator-proven commands (CLI shim over
 * the launcher IPC host, tray menu, desktop-shell shutdown) keep the original
 * unconditional supersede semantics. Window-level close transactions and
 * commands forwarded by the daemon through second-instance argv are not new
 * operator lifecycle decisions, so a stop from them must never abort an
 * in-flight restart (2026-08-29: a forwarded stop kept superseding a CLI
 * restart 1-5s in, so the restart never settled and the backend stayed down).
 */
type LauncherLifecycleProvenance = "operator" | "operator-restart" | "window-close" | "forwarded";

type LauncherLifecycleStopJoinDecision = {
  /**
   * beginIntent must join an in-flight restart instead of aborting it. The
   * caller turns a join into an accepted no-op result.
   */
  joinInFlightRestart: boolean;
  /**
   * Wait (bounded) for an in-flight restart to settle before creating the
   * lease, so the stop runs against the settled state instead of killing the
   * restart. Used by the window-close path, which still needs the backend
   * actually stopped afterwards.
   */
  waitForInFlightRestart: boolean;
};

/**
 * Only the plain "stop" operation relaxes its supersede semantics. force-stop
 * stays an explicit confirmed destructive intent and always supersedes, and
 * operator-proven stops keep superseding exactly as before.
 */
function joinDecisionForLauncherLifecycleStop(
  operation: string,
  provenance: LauncherLifecycleProvenance
): LauncherLifecycleStopJoinDecision {
  if (operation !== "stop") {
    return { joinInFlightRestart: false, waitForInFlightRestart: false };
  }
  if (provenance === "forwarded") {
    return { joinInFlightRestart: true, waitForInFlightRestart: false };
  }
  if (provenance === "window-close") {
    return { joinInFlightRestart: false, waitForInFlightRestart: true };
  }
  return { joinInFlightRestart: false, waitForInFlightRestart: false };
}

const RESTART_SETTLEMENT_POLL_INTERVAL_MS = 250;
const WORKBENCH_CLOSE_RESTART_JOIN_WAIT_MS = 90_000;

/**
 * A restart or rebuild-and-start lease is "in flight" while it occupies the
 * supervisor slot in intent phase (its stop+start mutation runs in that phase;
 * bindCommand only moves it to observing after the mutation settled). The wait
 * ends when the slot is gone (cleared after a failed mutation), is no longer a
 * restart/rebuild, or has left the intent phase.
 */
function inFlightRestartLeaseSettled(instanceId: string): boolean {
  const snapshot = launcherLifecycleSupervisor.snapshot(instanceId);
  const joinableMutation = snapshot !== null
    && (snapshot.operation === "restart" || snapshot.operation === "rebuild-and-start");
  return snapshot === null
    || !joinableMutation
    || snapshot.phase !== "intent";
}

function delayWithAbortSignal(timeoutMs: number, signal?: AbortSignal): Promise<void> {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, timeoutMs);
    const onAbort = (): void => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      const reason = signal?.reason;
      reject(reason instanceof Error ? reason : new Error("lifecycle wait aborted"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
    if (signal?.aborted) onAbort();
  });
}

async function waitForInFlightRestartSettlement(
  instanceId: string,
  timeoutMs: number,
  signal?: AbortSignal
): Promise<void> {
  const deadlineMs = Date.now() + timeoutMs;
  while (!inFlightRestartLeaseSettled(instanceId)) {
    signal?.throwIfAborted();
    if (Date.now() >= deadlineMs) {
      throw new Error(
        `In-flight Launcher restart/rebuild-and-start did not settle within ${Math.round(timeoutMs / 1000)}s; `
        + "the window close stop was not accepted because it must not abort a running mutation."
      );
    }
    await delayWithAbortSignal(
      Math.min(RESTART_SETTLEMENT_POLL_INTERVAL_MS, Math.max(1, deadlineMs - Date.now())),
      signal
    );
  }
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

async function closeOrchestratedWorkbenchWindow(instanceId: string): Promise<void> {
  const provider = windowProvider;
  if (provider === null) {
    return;
  }
  try {
    if (isCurrentCheckoutInstance(instanceId)) {
      await provider.approveWorkbenchCloseOnce();
    } else {
      await provider.closeInstanceWorkbench(instanceId);
    }
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  }
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
      WORKBENCH_START_READY_WAIT_MS,
      undefined,
      { present: !desktopCliArgs.hiddenPresentation }
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
  _timeoutMs: number,
  previousBackendIdentity?: ServingProcessIdentity | null,
  presentation: { present?: boolean } = {}
): Promise<void> {
  // I4b already waited for backend health before returning. Do not poll Python
  // runtime-manager result files: Electron main-line never writes them, so a
  // 90s wait used to block the workbench window after a successful start.
  if (!launcherLifecycleSupervisor.isCurrent(lease)) {
    return;
  }
  // Post-start build verification: never reopen the workbench on a stale or
  // unreplaced serving process (2026-09-11 freshness-gate incident).
  const servingVerification = await verifyRestartedServingVersion({
    workspaceRoot: paths.workspaceRoot,
    readiness: "shell",
    signal: lease.signal,
    previousBackendIdentity: previousBackendIdentity ?? null
  });
  lease.signal.throwIfAborted();
  if (!servingVerification.ok) {
    const detail = `Workbench serving verification failed after ${lease.instanceId} start: ${servingVerification.reason}`;
    console.error(detail);
    throw new Error(detail);
  }
  const verifiedPort = servingVerification.inspection?.port ?? 0;
  if (!Number.isInteger(verifiedPort) || verifiedPort <= 0 || verifiedPort > 65535) {
    throw new Error("Workbench serving verification did not return a valid port");
  }
  // This port was just proved by the health + identity + version handshake.
  // A second Python bridge only rereads the same persisted URL.
  const url = rememberLiveWorkbenchUrl(workbenchLoopbackUrl(verifiedPort));
  await resolveDesktopActionLoopContext(bootstrap, { signal: lease.signal });
  if (!launcherLifecycleSupervisor.isCurrent(lease) || !launcherLifecycleSupervisor.claimReady(lease)) {
    return;
  }
  try {
    await openWorkbenchAtCurrentLauncherUrl(paths, bootstrap, provider, {
      workbenchUrl: url, ...(presentation.present === false ? { present: false } : {})
    });
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

async function retireIsolatedBackendAfterStartFailure(input: {
  instanceId: string;
  workspaceRoot: string;
  generation: number;
  commandId: string;
  message: string;
  isCurrent?: () => boolean;
  signal?: AbortSignal;
  pythonPath: string;
}): Promise<void> {
  const registryPath = instancesRegistryPath();
  const registry = await readRegistry(registryPath);
  const entry = registry.instances[input.instanceId];
  const generation = Number(entry?.generation || 0);
  const status = String(entry?.status || "").trim().toLowerCase();
  const commandId = String(entry?.commandId || "").trim();
  const ownerPid = Number(entry?.ownerPid || 0);
  if (
    !entry
    || generation !== input.generation
    || commandId !== input.commandId
    || (ownerPid > 0 && ownerPid !== process.pid)
    || (status !== "starting" && status !== "restarting" && status !== "steady")
  ) {
    return;
  }
  const claimed = await claimStopIfGeneration(registryPath, {
    instanceId: input.instanceId,
    expectedGeneration: input.generation,
    expectedCommandId: input.commandId,
    projectRoot: String(entry.projectRoot || input.workspaceRoot || "").trim(),
    commandId: `retire-after-start-failure:${randomUUID()}`
  });
  if (!claimed.applied) {
    return;
  }
  const retired = await retireClaimedIsolatedRuntime({
    instanceId: input.instanceId,
    workspaceRoot: input.workspaceRoot,
    entry: claimed.entry,
    registryPath,
    signal: input.signal,
    pythonPath: input.pythonPath,
    isCurrent: input.isCurrent,
    desiredStateOnFailure: "open",
    successFailureMessage: input.message
  });
  await recordAdmissionOutcome({
    instanceId: input.instanceId,
    outcome: "failure"
  });
  if (!retired.ok) {
    throw new Error(retired.message);
  }
}

async function runIsolatedRegistryMutation(input: {
  operation: BranchInstanceOperation;
  instanceId: string;
  workspaceRoot: string;
  pythonPath: string;
  operatorConfigPath: string;
  signal?: AbortSignal;
  isCurrent?: () => boolean;
  interruptActiveWork?: boolean;
}): Promise<OrchestratedBranchInstanceResult> {
  if (input.operation === "observe-error" || input.operation === "observe-ready") {
    throw new Error("isolated observe must use instanceRegistryStore, not the Python bridge");
  }
  const payload = launcherStateStore.projectBranchInstances();
  const target = resolveIsolatedClaimTarget(payload, input.instanceId);

  if (input.operation === "start" || input.operation === "restart") {
    if (input.operation === "start" && target) {
      const inspectReuse = () => inspectIsolatedStartReuse({
        target, pythonPath: input.pythonPath, signal: input.signal
      });
      let reuse = await inspectReuse();
      if (reuse.kind === "pending") {
        await scheduleRegistryReconciliation(payload);
        reuse = await inspectReuse();
      }
      if (reuse.kind === "pending") {
        return {
          schemaVersion: 1, accepted: false, operation: input.operation,
          instanceId: input.instanceId, generation: reuse.generation,
          code: "instance_busy", message: "该分支进程仍在运行，启动记录正在核对，请稍后重试。"
        };
      }
      if (reuse.kind === "reuse") {
        return {
          schemaVersion: 1,
          accepted: true,
          operation: input.operation,
          instanceId: input.instanceId,
          commandId: String(reuse.entry.commandId),
          generation: Number(reuse.entry.generation),
          port: Number(reuse.entry.port),
          controlPort: Number(reuse.entry.controlPort),
          message: "正在打开该分支工作台窗口。"
        };
      }
    }
    if (target) {
      input.signal?.throwIfAborted();
      // Same build gate as the main line: publish "building" before the
      // await and clear it in a finally so an aborted or failed build cannot
      // leave the row stuck in building.
      await runWithFrontendBuildGate(
        input.instanceId,
        { operation: input.operation, notify: () => updateLauncherWindowTruth() },
        () => ensureFrontendRelease({
          workspaceRoot: target.projectRoot,
          pythonPath: input.pythonPath,
          signal: input.signal
        })
      );
      input.signal?.throwIfAborted();
      const claimed = await prepareIsolatedStart({
        instanceId: input.instanceId,
        branchInstances: payload,
        operation: input.operation,
        commandId: randomUUID(),
        pythonPath: input.pythonPath,
        signal: input.signal,
        isCurrent: input.isCurrent,
        interruptActiveWork: input.interruptActiveWork
      });
      if (!claimed.ok) {
        return {
          schemaVersion: 1,
          accepted: false,
          operation: input.operation,
          instanceId: input.instanceId,
          generation: claimed.generation,
          code: claimed.code,
          message: claimed.message
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
      // Capture the process owner synchronously after spawn. The workspace key
      // can already point at a newer job by the time identity/readiness awaits
      // settle, so cleanup must retain this exact generation's retirement.
      const retireOwnedJob = spawnPid > 0
        ? captureTrackedWorkbenchJobRetirement(target.projectRoot, spawnPid)
        : null;
      let spawnIdentity: Awaited<ReturnType<typeof capturePythonProcessIdentity>> = null;
      const retireSpawnedTree = async (): Promise<boolean> => {
        if (spawnPid <= 0) {
          return false;
        }
        if (retireOwnedJob && await retireOwnedJob()) {
          return true;
        }
        if (!spawnIdentity) {
          throw new Error(`isolated workbench backend process identity could not be captured for pid ${spawnPid}`);
        }
        const terminateProcessTree = createPythonOwnedProcessTreeTerminator({
          pythonPath: spawned.pythonPath,
          workspaceRoot: target.projectRoot,
          allowedKinds: ["managed_workbench_backend"],
          expectedIdentities: { [String(spawnPid)]: spawnIdentity }
        });
        if (!(await terminateProcessTree(spawnPid, spawnIdentity))) {
          throw new Error(`isolated workbench backend process-tree retirement was not verified for pid ${spawnPid}`);
        }
        return true;
      };
      try {
        if (spawnPid > 0 && generation > 0) {
          // Persist the PID before asynchronous identity capture. If capture or
          // later startup fails, the registry still retains a retirement-pending
          // handle unless this exact generation is superseded.
          const recorded = await recordSpawnPid(instancesRegistryPath(), {
            instanceId: input.instanceId,
            spawnPid,
            expectedGeneration: generation
          });
          if (!recorded.applied) {
            throw new Error(`isolated workbench backend spawn pid CAS missed for pid ${spawnPid}`);
          }
        }
        if (spawnPid > 0) {
          spawnIdentity = await capturePythonProcessIdentity({
            pythonPath: spawned.pythonPath,
            workspaceRoot: target.projectRoot,
            pid: spawnPid
          });
          if (!spawnIdentity) {
            throw new Error(`isolated workbench backend process identity could not be captured for pid ${spawnPid}`);
          }
        }
        if (spawnPid > 0 && generation > 0 && spawnIdentity) {
          const recorded = await recordSpawnPid(instancesRegistryPath(), {
            instanceId: input.instanceId,
            spawnPid,
            expectedGeneration: generation,
            spawnCreateTime: spawnIdentity.createTime,
            spawnExecutable: spawnIdentity.executable
          });
          if (!recorded.applied) {
            throw new Error(`isolated workbench backend spawn identity CAS missed for pid ${spawnPid}`);
          }
        }
        await waitForBackendHealthy({
          port,
          readiness: "shell",
          signal: input.signal,
          childError: () => {
            const spawnError = spawned.spawnError();
            return spawnError === null ? null : new Error(`isolated workbench backend failed to spawn: ${spawnError.message}`);
          },
          childAlive: () => {
            return spawned.child.exitCode == null && spawned.child.killed !== true;
          }
        });
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        try {
          const retirementProven = await retireSpawnedTree();
          const released = await waitForPortRelease({ port, host: "127.0.0.1" });
          if (!released) {
            throw new Error(`isolated workbench backend port ${port} remains occupied after spawn cleanup`);
          }
          if (retirementProven && spawnPid > 0 && generation > 0) {
            // A verified retirement of this captured owner is sufficient to
            // clear its handle, even when identity capture itself failed. CAS
            // prevents this compensation from clearing a replacement generation.
            await upsert(instancesRegistryPath(), input.instanceId, {
              spawnPid: 0,
              spawnCreateTime: 0,
              spawnExecutable: ""
            }, generation);
          }
          await retireIsolatedBackendAfterStartFailure({
            instanceId: input.instanceId,
            workspaceRoot: target.projectRoot,
            generation,
            commandId: String(claimed.entry.commandId || ""),
            message,
            pythonPath: input.pythonPath,
          });
        } catch (compensationError: unknown) {
          throw new Error(
            `${message}; isolated backend compensation failed: ${compensationError instanceof Error ? compensationError.message : String(compensationError)}`
          );
        }
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
    const stopCommandId = randomUUID();
    const claimed = await claimIsolatedStop({
      instanceId: input.instanceId,
      branchInstances: payload,
      commandId: stopCommandId
    });
    const stopWorkspaceRoot = String(
      target?.projectRoot
      || claimed.entry.projectRoot
    ).trim();
    const retired = await retireClaimedIsolatedRuntime({
      instanceId: input.instanceId,
      workspaceRoot: stopWorkspaceRoot,
      entry: claimed.entry,
      pythonPath: input.pythonPath,
      signal: input.signal,
      isCurrent: input.isCurrent,
      forceRetireOnActiveWorkRefusal: input.operation === "force-stop",
      interruptActiveWork: input.interruptActiveWork,
      desiredStateOnFailure: input.interruptActiveWork ? "open" : "closed"
    });
    const commandId = String(claimed.entry.commandId || stopCommandId);
    return {
      schemaVersion: 1,
      accepted: true,
      operation: input.operation,
      instanceId: input.instanceId,
      generation: Number(claimed.entry.generation || 0),
      commandId,
      ...(
        !retired.ok
          ? {
              code: "backend_retire_incomplete",
              message: retired.message
            }
          : {}
      )
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
  payload: LauncherIpcInvokePayload,
  provenance: LauncherLifecycleProvenance = "operator",
  signal?: AbortSignal
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
  const bodyRecord = typeof body === "object" && body !== null ? (body as Record<string, unknown>) : null;
  const instanceId = bodyRecord ? String(bodyRecord.instanceId ?? "").trim() : "";
  // Hidden presentation travels on the payload body: the isolated-start
  // supervisor must open this instance's window without show/focus when the
  // start request (e.g. `launcher --hidden`) carried the intent.
  const hiddenPresentation = bodyRecord?.hiddenPresentation === true;
  if (!instanceId) {
    throw new Error("branch instance id is required");
  }
  if (isCurrentCheckoutInstance(instanceId)) {
    const mainResult = await orchestrateLauncherLifecycle(operation, payload, provenance, signal);
    return { ...mainResult, instanceId };
  }
  const forceAuthorization = await authorizeLauncherForceLifecycle({
    operation,
    instanceId,
    payload,
    operatorIntent: payload.path || operation
  });
  signal?.throwIfAborted();
  const supervisedOperation = normalizeSupervisedLifecycleOperation(operation);
  const desiredState = desiredStateForLifecycleOperation(supervisedOperation);
  const intentLease = launcherLifecycleSupervisor.beginIntent({
    instanceId,
    operation: supervisedOperation,
    desiredState
  });
  const lifecycleSignal = signal
    ? AbortSignal.any([signal, intentLease.signal])
    : intentLease.signal;
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
      signal: lifecycleSignal,
      isCurrent: () => launcherLifecycleSupervisor.isCurrent(intentLease),
      interruptActiveWork: provenance === "operator-restart" || (operation === "restart" && provenance === "operator")
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
          await provider.openOrFocusInstanceWorkbench({
            instanceId,
            url,
            ...(hiddenPresentation ? { present: false } : {})
          });
        },
        closeWindowIfSuperseded: async () => {
          await closeWindowIfSupersededByClosedIntent(instanceId);
        },
        closeWindowAfterReadyFailure: async () => {
          if (provider !== null) {
            await provider.closeInstanceWorkbench(instanceId);
          }
        },
        retireBackend: async (message) => {
          await retireIsolatedBackendAfterStartFailure({
            instanceId,
            workspaceRoot: paths.workspaceRoot,
            generation: lease.generation,
            commandId: lease.commandId,
            message,
            pythonPath,
            isCurrent: () => launcherLifecycleSupervisor.isCurrent(lease),
            signal: lease.signal
          });
        },
        markReady: async (observedGeneration) => {
          const observed = await observeIsolatedReady({
            instanceId,
            expectedGeneration: observedGeneration
          });
          const alreadyReady = Number(observed.entry.generation) === observedGeneration
            && String(observed.entry.commandId || "") === lease.commandId
            && observed.entry.status === "steady" && observed.entry.phase === "steady"
            && observed.entry.desiredState === "open" && !observed.entry.cleanupInProgress;
          // Reuse and the reconciler can observe READY before this callback.
          // A matching settled command is success, never a reason to retire it.
          if (!observed.applied && !alreadyReady) {
            throw new Error(`isolated observe-ready CAS missed for ${instanceId}`);
          }
        },
        markError: async (observedGeneration, message) => {
          const observed = await observeIsolatedError({
            instanceId,
            expectedGeneration: observedGeneration,
            message
          });
          if (observed.applied || !launcherLifecycleSupervisor.isCurrent(lease)) {
            return;
          }
          const registryPath = instancesRegistryPath();
          const registry = await readRegistry(registryPath);
          const entry = registry.instances[instanceId];
          const status = String(entry?.status || "").trim().toLowerCase();
          const commandId = String(entry?.commandId || "").trim();
          if (
            !entry
            || Number(entry.generation || 0) !== observedGeneration
            || commandId !== lease.commandId
            || !["starting", "restarting", "steady"].includes(status)
          ) {
            return;
          }
          const repaired = await upsert(
            registryPath,
            instanceId,
            {
              status: "failed",
              phase: "failed",
              desiredState: "open",
              failureMessage: message
            },
            observedGeneration
          );
          if (!repaired.applied) {
            throw new Error(`isolated observe-error fallback lost registry generation for ${instanceId}`);
          }
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
    && !result.code
    && desiredState === "closed"
    && result.commandId
    && launcherLifecycleSupervisor.isCurrent(lease)
  ) {
    await closeOrchestratedWorkbenchWindow(instanceId);
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
    timeoutMs: launcherApiBridgeTimeoutMs(path, method),
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

async function reclaimExpiredIsolatedStops(): Promise<void> {
  if (!projectControlPlaneAutomaticLifecycle) return;
  const result = await reconcileOrphanedInstanceRegistry({
    registryPath: instancesRegistryPath(),
    pythonPath: desktopPythonPath()
  });
  if (result.retained.length > 0) {
    console.warn(
      `Isolated runtime reconciliation retained ${result.retained.length} in-flight registry row(s) because retirement was not verified.`
    );
  }
}

function scheduleLauncherStatusCliRefresh(): void {
  if (launcherBootstrap === null) {
    return;
  }
  void reclaimExpiredIsolatedStops()
    .catch((error: unknown) => {
      console.warn(error instanceof Error ? error.message : String(error));
    })
    .finally(() => {
      void launcherStateStore.refresh("launcher_status_refresh");
    });
}

/**
 * The Python runtime-manager daemon that used to fulfil deferred restart
 * intents is not started on the Electron-owned product path (ADR 0009 I6).
 * Electron main now polls the durable intents and executes the agreed
 * "restart when the active work ends" request through the same main-line
 * lifecycle entry the tray uses, so the promise made when the restart was
 * refused keeps holding.
 */
const DEFERRED_RESTART_FULFILLMENT_INTERVAL_MS = 10_000;

async function runDeferredRestartFulfillmentOnce(): Promise<void> {
  if (deferredRestartFulfillmentInFlight || launcherBootstrap === null) {
    return;
  }
  const paths = createDesktopPathsForApp();
  deferredRestartFulfillmentInFlight = true;
  try {
    await fulfillDeferredRestartIntentOnce({
      workspaceRoot: paths.workspaceRoot,
      runtimeManagerDir: resolveRuntimeManagerDir(paths.workspaceRoot),
      notBefore: projectControlPlaneRecoveryNotBefore,
      listActiveWork: () => listActiveWorkRuns(paths.workspaceRoot),
      submitRestart: async () =>
        await orchestrateLauncherLifecycle("restart", { schemaVersion: 1, path: "restart" }, "forwarded")
    });
  } catch (error: unknown) {
    console.warn(error instanceof Error ? error.message : String(error));
  } finally {
    deferredRestartFulfillmentInFlight = false;
  }
}

function startDeferredRestartFulfillment(): void {
  if (deferredRestartFulfillmentTimer !== null) {
    return;
  }
  deferredRestartFulfillmentTimer = setInterval(() => {
    void runDeferredRestartFulfillmentOnce();
  }, DEFERRED_RESTART_FULFILLMENT_INTERVAL_MS);
  deferredRestartFulfillmentTimer.unref?.();
}

function stopDeferredRestartFulfillment(): void {
  if (deferredRestartFulfillmentTimer !== null) {
    clearInterval(deferredRestartFulfillmentTimer);
    deferredRestartFulfillmentTimer = null;
  }
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
  const runtimeDir = dirname(launcherStatePath(paths.workspaceRoot));
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
      const watcher = watch(target, { persistent: false }, (_event, filename) => {
        // Runtime logs and atomic-write temporary files share this directory.
        // Only finalized state/port observations should trigger inventory work.
        if (target === runtimeDir && filename !== null
          && !["state.json", "ports.json"].includes(filename.toString())) return;
        scheduleLauncherStateFileHint();
      });
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
  launcherActiveReleaseWatcher?.stop();
  launcherActiveReleaseWatcher = null;
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
    restartLatestShell: () => restartLauncherToLatestBuild(),
    orchestrateLauncherApi: async (path, payload) => {
      const result = path === "freshness" ? await currentLauncherUpdateFreshness() : await orchestrateLauncherApi(path, payload);
      if (String(payload.init?.method ?? "GET").toUpperCase() !== "GET") {
        scheduleLauncherStatusCliRefresh();
      }
      return result;
    },
    resolveLocalStatus: () => launcherStateStore.projectStatus(),
    resolveLocalBranchInstances: () => launcherStateStore.projectBranchInstances(),
    resolveLifecycleInFlight: (instanceId) => {
      const snapshot = launcherLifecycleSupervisor.snapshot(instanceId);
      return snapshot === null
        ? null
        : { operation: snapshot.operation, phase: snapshot.phase };
    }
  });
  return launcherIpcHost;
}

ipcMain.handle(IPC_CHANNELS.launcherInvoke, async (event, payload: LauncherIpcInvokePayload) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return await resolveLauncherIpcHost().invoke(payload);
});

// The workbench window has no launcherInvoke bridge; this narrow verb lets it
// reach the same restart orchestration as the Launcher panel without widening
// the general Launcher IPC surface. The payload must mirror what the panel
// renderer sends for "restart" so the web side can normalize both answers alike.
ipcMain.handle(IPC_CHANNELS.requestWorkbenchRestart, async (event, trigger?: string) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  const normalizedTrigger = String(trigger ?? "").trim();
  return await resolveLauncherIpcHost().invoke({
    schemaVersion: 1,
    path: "restart",
    init: {
      method: "POST",
      ...(normalizedTrigger ? { headers: { "X-Vibelution-Launcher-Trigger": normalizedTrigger } } : {})
    }
  });
});

// Advisory shell staleness (frontend snapshot behind, window still usable)
// is not a workbench restart. This verb is the update banner's explicit
// request to replace the resident shell.
ipcMain.handle(IPC_CHANNELS.requestWorkbenchShellUpdate, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins());
  return await resolveLauncherIpcHost().invoke({
    schemaVersion: 1,
    path: "restart-latest-shell",
    init: { method: "POST" }
  });
});

ipcMain.handle(IPC_CHANNELS.requestWindowClose, (event) => {
  const provider = windowProvider;
  if (provider === null) throw new Error("Managed window provider is unavailable.");
  return requestRendererWindowClose(event,
    () => BrowserWindow.fromWebContents(event.sender),
    (windowId, senderUrl) => provider.requestRendererWorkbenchClose(windowId, senderUrl));
});

ipcMain.handle(IPC_CHANNELS.getLauncherFreshness, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  return await currentLauncherUpdateFreshness();
});

ipcMain.handle(IPC_CHANNELS.showLauncherWindow, async (event) => {
  assertTrustedIpcSender(event, trustedIpcOrigins(event));
  if (windowProvider === null) {
    throw new Error("Launcher window is unavailable.");
  }
  return await windowProvider.openLauncher();
});

ipcMain.handle(IPC_CHANNELS.getLauncherState, (event) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  return launcherStateStore.snapshot();
});

ipcMain.handle(IPC_CHANNELS.refreshLauncherState, async (event) => {
  assertTrustedIpcSender(event, launcherIpcTrustedOrigins());
  await reclaimExpiredIsolatedStops();
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
  try {
    await startOrFocusWorkbenchFromProductEntry({
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

async function applyPendingProjectSlot(
  projectRoot: string,
  lifecycleCommand = "",
  provenance: LauncherLifecycleProvenance = "operator",
  options: { hiddenPresentation?: boolean; launchRequestId?: string; workspaceRoot?: string } = {}
): Promise<void> {
  const hiddenPresentation = options.hiddenPresentation === true;
  const wanted = projectRoot.trim();
  if (!wanted) {
    return;
  }
  let receipt: ReturnType<typeof beginLaunchRequestReceipt> | null = null;
  try {
    // The native entry's integration workspace and selected slot are distinct.
    // Legacy envelopes may use the installed profile; never guess from a slot.
    if (!await ensureProjectControlPlane(options.workspaceRoot || "")) throw new Error("PROJECT_CONTROL_PLANE_UNAVAILABLE");
    receipt = beginLaunchRequestReceipt({
      shellRoot: createDesktopPathsForApp().workspaceRoot,
      projectRoot: wanted, operation: lifecycleCommand, requestId: options.launchRequestId
    });
    if (receipt.duplicate) return;
    if (windowProvider === null || launcherBootstrap === null) {
      // A second-instance launch can arrive while the primary Electron shell is
      // still bootstrapping. Wait for the same control-plane boundary instead of
      // dropping the lifecycle command after merely starting Electron.
      await launcherControlPlaneReady;
    }
    const provider = windowProvider;
    if (provider === null || launcherBootstrap === null) {
      pendingProjectRoot = wanted;
      receipt.failed("launcher_unavailable", "Launcher 控制面不可用，启动未执行。");
      return;
    }
    pendingProjectRoot = "";
    const requested = lifecycleCommand.trim().toLowerCase();
    if (!hiddenPresentation && PROJECT_SLOT_LIFECYCLE_COMMANDS.has(requested)
      && normalizeInstanceKey(wanted) === normalizeInstanceKey(createDesktopPathsForApp().workspaceRoot)) {
      // The shell already owns this exact project. Its lifecycle verifies the
      // backend and opens the window; unrelated inventory cannot admit it.
      const result = await orchestrateLauncherLifecycle(requested, {
        schemaVersion: 1,
        path: "project-slot"
      }, provenance);
      if (!result.accepted) {
        receipt.failed(result.code || "lifecycle_rejected", result.message || "Launcher 拒绝了生命周期请求。");
        return;
      }
      receipt.dispatched();
      return;
    }
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
      let result: { accepted: boolean; code?: string; message?: string };
      if (plan.isMain) {
        result = await orchestrateLauncherLifecycle(plan.operation, {
          schemaVersion: 1,
          path: "project-slot"
        }, provenance);
      } else {
        result = await orchestrateBranchInstanceLifecycle(plan.operation, {
          schemaVersion: 1,
          path: `branch-instances/${plan.operation}`,
          init: {
            method: "POST",
            body: {
              instanceId: plan.instanceId,
              ...(hiddenPresentation ? { hiddenPresentation: true } : {})
            }
          }
        }, provenance);
      }
      if (!result.accepted) {
        receipt.failed(result.code || "lifecycle_rejected", result.message || "Launcher 拒绝了生命周期请求。");
        return;
      }
    }
    receipt.dispatched();
    const windowAction = projectSlotWindowAction(plan);
    if (windowAction === "none") {
      // The isolated-start supervisor opens the instance-scoped window only
      // after that generation passes HTTP readiness. Opening the shared
      // Workbench window here leaves an unowned ghost window after stop.
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
    if (windowAction === "instance") {
      await provider.openOrFocusInstanceWorkbench({
        instanceId: plan.instanceId,
        url,
        ...(hiddenPresentation ? { present: false } : {})
      });
      return;
    }
    currentWorkbenchUrl = url;
    markWorkbenchOpenRequested();
    await provider.openOrFocusWorkbench(url);
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    receipt?.failed("launch_preparation_failed", detail);
    notifyDesktopTray("Vibelution", `应用工作区失败：${detail.slice(0, 300)}`, "warning");
  } finally {
    startProjectControlPlaneObservers();
  }
}

/** A single project control plane can attach after the resident assistant. */
async function ensureProjectControlPlane(workspaceRoot = "", managementOnly = false): Promise<boolean> {
  if (projectControlPlaneStartup !== null) return await projectControlPlaneStartup;
  if (launcherBootstrap !== null && windowProvider !== null) return true;
  let deferredWorkspace = "";
  projectControlPlaneStartup = (async () => {
    await app.whenReady();
    if (shutdownApproved) return false;
    const current = desktopLaunchSettings();
    const deferred = current.assistant === true || !current.workspaceRoot;
    projectControlPlaneAutomaticLifecycle = !managementOnly;
    projectControlPlaneRecoveryNotBefore = managementOnly ? Date.now() : undefined;
    if (deferred) {
      projectControlPlaneLaunchSettings = resolveDeferredProjectLaunchSettings({
        env: process.env, cliArgs: desktopCliArgs, resourcesRoot: process.resourcesPath,
        userDataRoot: app.getPath("userData"),
      }, workspaceRoot, current.configPath);
    }
    const paths = createDesktopPathsForApp();
    if (deferred) {
      deferredWorkspace = paths.workspaceRoot;
      claimElectronDesktopShellOwner(deferredWorkspace);
    }
    // Opening a project must not relaunch the already-resident assistant.
    await bootstrapProjectControlPlane(paths, !deferred, !managementOnly);
    if (launcherBootstrap === null || windowProvider === null || shutdownApproved) return false;
    assistantOnly = false;
    return true;
  })();
  try { return await projectControlPlaneStartup; }
  catch (error) {
    // A failed first human selection must not poison future attempts or leave
    // that project claiming a live control plane. Never undo a published owner.
    if (launcherBootstrap === null && windowProvider === null) {
      try { if (deferredWorkspace) releaseElectronDesktopShellOwner(deferredWorkspace); }
      catch { console.warn("ASSISTANT_PROJECT_OWNER_RELEASE_FAILED"); }
      projectControlPlaneLaunchSettings = null;
      projectControlPlaneStartup = null;
    }
    throw error;
  }
}

async function bootstrapProjectControlPlane(paths: DesktopPaths, allowShellRefresh = true, restoreLifecycle = true): Promise<void> {
  if (restoreLifecycle) {
    await reapManagedRuntimeOnDesktopStart({
      stopManagedRuntime,
      stopLeftoverPythonLauncher: stopOwnedPythonLauncherService,
      recordEvent: async (event) => {
        await recordElectronSupervisorEvent(launcherBootstrap, event);
      }
    });
    await reclaimExpiredIsolatedStops();
  }
  if (desktopCliArgs.smoke) {
    await runSmokeAndQuit(paths);
    return;
  }
  // URL discovery is read-only and independent of shell readiness. Publish
  // the control plane only after readiness; retire the child on refresh/error.
  const initialWorkbenchUrlController = new AbortController();
  const initialWorkbenchUrl = resolveInitialWorkbenchUrl(paths, initialWorkbenchUrlController.signal);
  let deepLinkRegistration: ReturnType<typeof registerPackagedDeepLinks>;
  try {
    if (allowShellRefresh && await refreshPackagedDesktopShellIfStale(thenLifecycleFromDesktopCli(desktopCliArgs))) {
      return;
    }
    deepLinkRegistration = registerPackagedDeepLinks(paths);
    launcherBootstrap = await bootstrapMainOwnedLauncher(paths, initialWorkbenchUrl);
  } finally {
    initialWorkbenchUrlController.abort();
    await initialWorkbenchUrl;
  }
  electronStartupStage = "tray_ready";
  const trayStartedAtMs = performance.now();
  windowProvider = createWindowProvider(paths, launcherBootstrap);
  resolveLauncherControlPlaneReady?.();
  resolveLauncherControlPlaneReady = null;
  // Publish only for a real, ready Windows product shell. Node-based main
  // tests and unmigrated layouts cannot touch an operator's runtime files.
  if (app.isPackaged && process.platform === "win32" && process.versions.electron) {
    try {
      const runtimeHome = resolveActiveCanonicalRuntimeHome(paths.workspaceRoot);
      if (runtimeHome) {
        const transport = await startNativeLauncherStartTransport({
          workspaceRoot: paths.workspaceRoot,
          runtimeDir: join(runtimeHome, "launcher"),
          identity: captureElectronOwnerIdentity(),
          onStart: async () => {
            try {
              return await orchestrateLauncherLifecycle(
                "start", { schemaVersion: 1, path: "start" }, "operator", undefined, undefined, true
              );
            } catch (error: unknown) {
              console.warn(error instanceof Error ? error.message : String(error));
              return { schemaVersion: 1, accepted: false, operation: "start", code: "native_start_failed",
                message: "Launcher 未确认启动成功，请查看控制面日志。" };
            }
          }
        });
        const retireTransport = () => { void transport.close().catch(() => undefined); };
        app.once("quit", retireTransport);
        process.once("exit", retireTransport);
      }
    } catch {
      console.warn("Native start transport unavailable; the compatibility entry remains active.");
    }
  }
  updateLauncherWindowTruth();
  // Management attachment cannot replay an earlier request. A later explicit
  // restart retains the normal lifecycle rules for superseding old requests.
  startDeferredRestartFulfillment();
  desktopTray?.destroy();
  desktopTray = createDesktopTray(paths, {
    openAssistant: () => {
      if (launcherAssistantWindow) void launcherAssistantWindow.open().catch(() => console.warn("ASSISTANT_WINDOW_FAILED"));
      else showAssistantStartupWait?.();
    },
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
  if (restoreLifecycle) startPeriodicShellFreshnessWatch();
  if (restoreLifecycle) {
    startWorkbenchBackendWatchdogLoop();
    void maybeRestoreTrayRestartAllPending();
  }
  const trayStartupEvents: RuntimeSceneElectronEvent[] = [{
    eventCode: "electron.tray.created",
    message: "Electron system tray created.",
    fields: { provider: "electron" }
  }, {
    eventCode: "electron.launcher.supervisor.started",
    message: "Electron launcher supervisor started.",
    fields: {
      provider: "electron",
      deepLinkRegistrationAttempted: deepLinkRegistration.attempted,
      deepLinkRegistrationRegistered: deepLinkRegistration.registered,
      deepLinkRegistrationReason: deepLinkRegistration.reason
    }
  }, {
    eventCode: "electron.launcher_service.started",
    message: "Electron main is the Launcher control plane; leftover Python launcher is not attached.",
    fields: {
      mode: launcherBootstrap?.mode ?? "",
      launcherBackendPid: launcherBootstrap?.launcherBackendPid ?? 0
    }
  }, {
    eventCode: "electron.tray.ready",
    message: "Lightweight tray started.",
    fields: electronStartupFields({
      provider: "electron",
      stage: "tray_ready",
      stageDurationMs: electronStageElapsedMs(trayStartedAtMs)
    })
  }];
  // Capture the ready timestamp now; observational I/O must not delay first open.
  scheduleTelemetryWithoutWaiting(async () => {
    for (const event of trayStartupEvents) {
      await recordElectronSupervisorEvent(launcherBootstrap, event);
    }
  });
}

function startProjectControlPlaneObservers(): void {
  if (projectControlPlaneObserversStarted) return;
  if (launcherBootstrap === null || windowProvider === null || shutdownApproved) {
    return;
  }
  projectControlPlaneObserversStarted = true;
  // Startup state writes must not launch full Git/status scans alongside
  // backend admission. One fresh read also covers hints missed meanwhile.
  const paths = createDesktopPathsForApp();
  startLauncherStateFileHints(paths);
  if (!app.isPackaged) {
    // Install after hints: their reset also disposes this release watcher.
    launcherActiveReleaseWatcher = startLauncherActiveReleaseWatcher({
      buildsRoot: join(paths.workspaceRoot, "web", ".vibelution-builds"),
      onChange: () => {
        windowProvider?.refreshLauncherIfReleaseChanged();
      }
    });
    windowProvider.refreshLauncherIfReleaseChanged();
  }
  scheduleLauncherStatusCliRefresh();
}

if (runPrimaryWhenReady) {
app.whenReady()
  .then(async () => {
    const workspaceRoot = String(desktopEnvironment().VIBELUTION_WORKSPACE_ROOT || "").trim();
    assistantOnly = desktopCliArgs.assistant === true || !workspaceRoot;
    // An empty project registry is valid for the packaged resident assistant.
    // Project-only paths are constructed only after this independent startup.
    const paths: DesktopPaths = workspaceRoot ? createDesktopPathsForApp() : {
      schemaVersion: 1, desktopBundleRoot: resolveDesktopBundleRoot(import.meta.url), resourcesRoot: process.resourcesPath,
      userDataRoot: app.getPath("userData"), workspaceRoot: "",
    };
    if (workspaceRoot) claimElectronDesktopShellOwner(paths.workspaceRoot);
    if (localDebuggingEnabled) {
      try {
        const retireDebugging = await publishLocalDebugging(app.getPath("userData"), paths.workspaceRoot, captureElectronOwnerIdentity(),
          workspaceRoot ? undefined : join(paths.userDataRoot, "assistant", "desktop_debug.json"));
        app.once("quit", retireDebugging);
      } catch (error) {
        console.warn("Local desktop debugging unavailable", error);
      }
    }
    const launcherDistRootInput = {
      resourcesRoot: paths.resourcesRoot,
      workspaceRoot: paths.workspaceRoot,
      packaged: app.isPackaged,
      env: desktopEnvironment()
    };
    registerLauncherAppProtocolHandle({
      // Resolve per request: the shell stays resident in the tray while
      // frontend rebuilds switch the active release pointer.
      resolveDistRoot: () => resolveLauncherDistRoot({ ...launcherDistRootInput,
        workspaceRoot: String(desktopEnvironment().VIBELUTION_WORKSPACE_ROOT || ""), env: desktopEnvironment() })
    });
    if (!desktopCliArgs.smoke) {
      const assistantStartup = startLauncherAssistant(paths);
      if (assistantOnly) {
        await assistantStartup;
        return;
      }
      void assistantStartup.catch(() => console.warn("ASSISTANT_START_FAILED"));
    }
    if (!await ensureProjectControlPlane(workspaceRoot)) return;
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
    }
    if (deferWorkbenchOpen) {
      pendingOpenWorkbenchRequest = false;
    }
    if (desktopCliArgs.workbenchCloseCanary) {
      if (launcherBootstrap === null || windowProvider === null) {
        throw new Error("Launcher bootstrap is unavailable for workbench close canary.");
      }
      await openWorkbenchForCloseCanary(paths, launcherBootstrap, windowProvider);
      return;
    }
    if (pendingProjectRoot) {
      await applyPendingProjectSlot(pendingProjectRoot, firstLifecycle, desktopLifecycleProvenance, {
        launchRequestId: desktopCliArgs.launchRequestId,
        hiddenPresentation: desktopCliArgs.hiddenPresentation
      });
    } else if (firstLifecycle && firstLifecycle !== "status" && windowProvider !== null) {
      if (firstLifecycle === "open") {
        pendingOpenWorkbenchRequest = false;
        markWorkbenchOpenRequested();
        await startOrFocusWorkbenchFromProductEntryOnShell().catch((error: unknown) => {
          console.warn(error instanceof Error ? error.message : String(error));
        });
      } else {
        await handleSecondInstanceLifecycleCommand(firstLifecycle, desktopLifecycleProvenance);
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
  .finally(() => {
    startProjectControlPlaneObservers();
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
    // Project bootstrap failure must not tear down the independent assistant.
    await launcherAssistantStarting?.catch(() => undefined);
    if (!launcherAssistantHost) app.quit();
  });
}

app.on("second-instance", (_event, argv, _workingDirectory, additionalData) => {
  const secondInstanceProvenance = resolveSingleInstanceProvenance(additionalData);
  try {
    const secondCli = resolveSingleInstanceCliIntent(additionalData);
    const intent = resolveSecondInstanceIntent({
      assistant: secondCli.assistant,
      deepLinkUrl: findVibelutionDeepLinkArg(argv) ?? "",
      projectRoot: secondCli.projectRoot,
      openWorkbench: secondCli.openWorkbench,
      hiddenPresentation: secondCli.hiddenPresentation,
      lifecycleCommand: secondCli.lifecycleCommand
    });
    if (intent.action === "open_assistant") {
      void requestOpenAssistantFromSecondInstance(intent.hiddenPresentation).catch(() => console.warn("ASSISTANT_WINDOW_FAILED"));
      return;
    }
    if (intent.action === "handle_deep_link") {
      void handlePublicDeepLinkUrl(intent.rawUrl, "second_instance");
      return;
    }
    if (intent.action === "apply_project") {
      void applyPendingProjectSlot(intent.projectRoot, intent.lifecycleCommand, secondInstanceProvenance, {
        launchRequestId: secondCli.launchRequestId,
        workspaceRoot: secondCli.workspaceRoot,
        hiddenPresentation: intent.hiddenPresentation
      }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
      return;
    }
    if (intent.action === "lifecycle") {
      void ensureProjectControlPlane(secondCli.workspaceRoot).then(ready => ready
        ? handleSecondInstanceLifecycleCommand(intent.command, secondInstanceProvenance) : undefined).finally(() => {
          startProjectControlPlaneObservers();
        }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
      return;
    }
    if (intent.action === "open_workbench") {
      void ensureProjectControlPlane(secondCli.workspaceRoot).then(ready => ready
        ? requestOpenWorkbenchFromSecondInstance() : undefined).finally(() => {
          startProjectControlPlaneObservers();
        }).catch((error: unknown) => {
        console.warn(error instanceof Error ? error.message : String(error));
      });
      return;
    }
    if (intent.action === "focus_existing_shell") {
      focusExistingDesktopShell();
    }
  } catch {
    console.warn("ASSISTANT_MODE_CONFLICT");
  }
});

async function handleSecondInstanceLifecycleCommand(
  command: string,
  provenance: LauncherLifecycleProvenance = "operator"
): Promise<void> {
  if (assistantOnly) { focusExistingDesktopShell(); return; }
  if (launcherBootstrap === null || windowProvider === null) {
    // Electron emits second-instance after ready, but the primary app may not
    // have finished its asynchronous Launcher bootstrap yet.
    await launcherControlPlaneReady;
  }
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
        { schemaVersion: 1, path: "toggle" },
        provenance
      );
    } catch (error: unknown) {
      notifyDesktopTray("Vibelution", `切换失败：${error instanceof Error ? error.message.slice(0, 220) : String(error)}`, "warning");
    }
    return;
  }
  if (command === "close-window") {
    // Window-level close intent forwarded by the Runtime Manager queue
    // (browser-missing auto-close and request-exit enqueue close_workbench
    // without stopManager). It runs the same controlled workbench close
    // transaction the workbench window close button uses - never an app-shell
    // "stop", and entirely in-process: no console window is created and no
    // subprocess is spawned on this lane.
    try {
      await requestTransactionalWorkbenchClose(createDesktopPathsForApp(), launcherBootstrap);
    } catch (error: unknown) {
      const detail = error instanceof Error ? error.message : String(error);
      notifyDesktopTray("Vibelution", `关闭工作台失败：${detail.slice(0, 300)}`, "warning");
    }
    return;
  }
  const operation = command === "rebuild-and-start" ? "rebuild-and-start" : command;
  try {
    await orchestrateLauncherLifecycle(operation, { schemaVersion: 1, path: command }, provenance);
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
  if (assistantOnly) shutdownApproved = true;
  if (shutdownApproved && launcherAssistantStarting && !launcherAssistantExitReady) {
    event.preventDefault();
    void stopLauncherAssistant().then(() => app.quit()).catch(() => console.warn("ASSISTANT_STOP_FAILED"));
    return;
  }
  if (shutdownApproved) {
    if (!assistantOnly) releaseElectronDesktopShellOwner(createDesktopPathsForApp().workspaceRoot);
    stopLauncherStateFileHints();
    stopDeferredRestartFulfillment();
    desktopTray?.destroy();
    desktopTray = null;
    stopDesktopActionLoop();
    stopWorkbenchBackendWatchdogLoop();
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
  stopDeferredRestartFulfillment();
  stopWorkbenchBackendWatchdogLoop();
});
