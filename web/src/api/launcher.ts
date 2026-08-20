import { fetchJson } from "./client";
import type {
  LauncherDeveloperCleanupAction,
  LauncherDeveloperCleanupApplyRequest,
  LauncherDeveloperCleanupApplyResponse,
  LauncherDeveloperCleanupPreviewResponse,
  LauncherDeveloperModeSetting,
  LauncherDeveloperModeUpdateRequest,
  LauncherDeveloperModeUpdateResponse,
  LauncherDeveloperNoiseOverview,
  LauncherMaintenanceApplyRequest,
  LauncherMaintenanceApplyResponse,
  LauncherMaintenancePreviewRequest,
  LauncherMaintenancePreviewResponse,
  LauncherMaintenanceSummary,
  LauncherControlResponse,
  LauncherOperation,
  LauncherStartupSettings as BaseLauncherStartupSettings,
  LauncherStatus as BaseLauncherStatus,
  RuntimeLifecycleCancelRequest,
  RuntimeLifecycleCancelResponse,
  RuntimeSummary,
  WorkbenchWindowModeSetting,
  WorkbenchWindowModeUpdateRequest,
  WorkbenchWindowModeUpdateResponse,
} from "./types";

export const LAUNCHER_ENDPOINT = "/api/launcher";
export const LAUNCHER_IPC_HOST_NOT_READY = "LAUNCHER_IPC_HOST_NOT_READY";

export class LauncherControlPlaneNotReadyError extends Error {
  readonly code = LAUNCHER_IPC_HOST_NOT_READY;

  constructor(message: string) {
    super(message);
    this.name = "LauncherControlPlaneNotReadyError";
  }
}

export function isLauncherControlPlaneNotReady(error: unknown) {
  return error instanceof LauncherControlPlaneNotReadyError;
}

type LauncherIpcInvokeResult =
  | { ok: true; payload: unknown }
  | { ok: false; error: { code: string; message: string } };

type LauncherIpcInvokePayload = {
  schemaVersion: 1;
  path: string;
  init?: {
    method?: "GET" | "POST" | "PUT" | "DELETE";
    headers?: Record<string, string>;
    body?: unknown;
  };
};

type LauncherIpcBridge = {
  launcherInvoke: (payload: LauncherIpcInvokePayload) => Promise<LauncherIpcInvokeResult>;
  getLauncherState?: () => Promise<LauncherStateSnapshotV1>;
  refreshLauncherState?: () => Promise<LauncherStateSnapshotV1>;
  onLauncherStateChanged?: (listener: (snapshot: LauncherStateSnapshotV1) => void) => () => void;
};

function launcherIpcBridge(): LauncherIpcBridge | null {
  if (typeof window === "undefined") {
    return null;
  }
  const globalLike = globalThis as { vibelutionLauncher?: unknown };
  const bridge = globalLike.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return null;
  }
  const launcherInvoke = (bridge as Partial<LauncherIpcBridge>).launcherInvoke;
  if (typeof launcherInvoke !== "function") {
    return null;
  }
  const stateBridge = bridge as Partial<LauncherIpcBridge>;
  return {
    launcherInvoke,
    ...(typeof stateBridge.getLauncherState === "function" ? { getLauncherState: stateBridge.getLauncherState } : {}),
    ...(typeof stateBridge.refreshLauncherState === "function"
      ? { refreshLauncherState: stateBridge.refreshLauncherState }
      : {}),
    ...(typeof stateBridge.onLauncherStateChanged === "function"
      ? { onLauncherStateChanged: stateBridge.onLauncherStateChanged }
      : {}),
  };
}

export function hasLauncherIpcBridge() {
  return launcherIpcBridge() !== null;
}

export type LauncherStateFreshness = "fresh" | "refreshing" | "stale";

export type LauncherRegistryReconciliationItem = {
  instanceId: string;
  classification: "healthy" | "stale" | "orphan" | "conflict" | "unknown";
  reasons: string[];
  windowOpen: boolean;
  listener: string[];
  ports: number[];
  portLeaseStatus?: string;
  firstObservedAt?: string;
  nextReconcileAt?: string;
};

export type LauncherWorktreeDryRunItem = {
  instanceId: string;
  projectRoot: string;
  branch: string;
  reason: string;
  action: "dry_run_only";
  dirty: boolean;
  mergedToMain: boolean;
  risks: string[];
};

export type LauncherStateSnapshotV1 = {
  schemaVersion: 1;
  revision: number;
  observedAt: string;
  freshness: LauncherStateFreshness;
  staleReason?: string;
  nextReconcileAt?: string;
  main: {
    id: string;
    observedState: string;
    desiredState: string;
    phase: string;
    commandId: string;
    generation: number;
    window: { open: boolean; rendererProcessId: number };
  };
  instances: Array<{
    id: string;
    observedState: string;
    desiredState: string;
    phase: string;
    commandId: string;
    generation: number;
    window: { open: boolean; rendererProcessId: number };
  }>;
  cleanup: {
    reconciliation: { active: boolean; reason: string; startedAt?: string };
    lastCompletedAt?: string;
    cleanedCount: number;
    skippedCount: number;
    failedCount: number;
    classifications: LauncherRegistryReconciliationItem[];
    portConflicts: LauncherRegistryReconciliationItem[];
    removedInstanceIds: string[];
    worktreeDryRun: LauncherWorktreeDryRunItem[];
    orphanCriteria: string[];
  };
};

export function hasLauncherStateBridge() {
  return typeof launcherIpcBridge()?.getLauncherState === "function";
}

export function getLauncherState(): Promise<LauncherStateSnapshotV1> {
  const bridge = launcherIpcBridge();
  if (typeof bridge?.getLauncherState !== "function") {
    throw new Error("Launcher state snapshot bridge is not available.");
  }
  return bridge.getLauncherState();
}

export function hasLauncherStateRefreshBridge() {
  return typeof launcherIpcBridge()?.refreshLauncherState === "function";
}

export function refreshLauncherState(): Promise<LauncherStateSnapshotV1> {
  const bridge = launcherIpcBridge();
  if (typeof bridge?.refreshLauncherState !== "function") {
    throw new Error("Launcher state refresh bridge is not available.");
  }
  return bridge.refreshLauncherState();
}

export function onLauncherStateChanged(listener: (snapshot: LauncherStateSnapshotV1) => void): () => void {
  const bridge = launcherIpcBridge();
  if (typeof bridge?.onLauncherStateChanged !== "function") {
    return () => undefined;
  }
  return bridge.onLauncherStateChanged(listener);
}

function ipcInitForRequest(init?: RequestInit): LauncherIpcInvokePayload["init"] | undefined {
  if (!init) {
    return undefined;
  }
  const method = String(init.method ?? "GET").toUpperCase() as "GET" | "POST" | "PUT" | "DELETE";
  if (!["GET", "POST", "PUT", "DELETE"].includes(method)) {
    return undefined;
  }
  const headers: Record<string, string> = {};
  if (init.headers) {
    const source = new Headers(init.headers);
    source.forEach((value, key) => {
      headers[key] = value;
    });
  }
  return {
    method,
    ...(Object.keys(headers).length > 0 ? { headers } : {}),
    ...(init.body !== undefined && init.body !== null ? { body: JSON.parse(String(init.body)) } : {}),
  };
}

async function invokeLauncherJson<T>(path: string, init?: RequestInit): Promise<T> {
  const bridge = launcherIpcBridge();
  if (bridge === null) {
    throw new Error("Launcher IPC bridge is not available.");
  }
  const result = await bridge.launcherInvoke({
    schemaVersion: 1,
    path,
    ...(ipcInitForRequest(init) ? { init: ipcInitForRequest(init) } : {}),
  });
  if (result.ok) {
    return result.payload as T;
  }
  if (result.error.code === LAUNCHER_IPC_HOST_NOT_READY) {
    throw new LauncherControlPlaneNotReadyError(result.error.message);
  }
  throw new Error(result.error.message || `Launcher IPC request failed: ${result.error.code}`);
}

type WorkbenchWindowSizeOption = {
  size: string;
  label: {
    zh: string;
    en: string;
  };
};

export type LauncherStartupSettings = Omit<BaseLauncherStartupSettings, "workbench"> & {
  launcher: {
    controlPort: number;
    effectiveControlPort: number;
    controlPortEnvOverride: number;
  };
  workbench: BaseLauncherStartupSettings["workbench"] & {
    windowSize: string;
    effectiveWindowSize: string;
    windowSizeEnvOverride: string;
    windowSizeOptions: WorkbenchWindowSizeOption[];
  };
};

export type LauncherStatus = Omit<BaseLauncherStatus, "settings"> & {
  settings?: {
    startup?: LauncherStartupSettings;
    workbenchWindow?: WorkbenchWindowModeSetting;
    developerMode?: LauncherDeveloperModeSetting;
  };
};

export type LauncherBranchInstanceRuntime = {
  lifecycleState: "closed" | "starting" | "running" | "stopping" | "restarting" | "partial" | "error";
  desiredState: string;
  observedState: string;
  phase: string;
  backend: {
    alive: boolean;
    healthy: boolean;
    listening: boolean;
    port: number;
    portReserved: boolean;
    portConflict: boolean;
    pid: number;
  };
  frontend: {
    mode: "bundled_static_dist" | "dev_server" | string;
    ready: boolean;
  };
  window: {
    open: boolean;
    pid: number;
    title: string;
    titleObserved: boolean;
  };
  error?: {
    code: string;
    message: string;
  };
  registryClassification?: "healthy" | "stale" | "orphan" | "conflict" | "unknown";
  portLeaseStatus?: string;
  firstObservedAt?: string;
  nextReconcileAt?: string;
};

export type LauncherBranchInstance = {
  id: string;
  kind: "main" | "worktree" | "local_branch" | "retired" | string;
  branch: string;
  path: string;
  displayPath: string;
  head: string;
  current: boolean;
  legacy: boolean;
  dirty: boolean;
  checkedOut: boolean;
  alive: boolean;
  observedState: string;
  port: number;
  controlPort?: number;
  url?: string;
  slotKey?: string;
  slotId?: string;
  dataHome?: string;
  shortName?: string;
  workbenchTitle?: string;
  launcherTitle?: string;
  pids: {
    backend: number;
    window: number;
    manager: number;
  };
  promotable: boolean;
  mergedToMain?: boolean;
  cleanupEligible?: boolean;
  cleanupRisks?: string[];
  runtime: LauncherBranchInstanceRuntime;
  startable: boolean;
  startBlockReason?: string;
  admissionRetryAfterMs?: number;
  admissionMessage?: string;
  portLeaseStatus?: string;
};

export type LauncherBranchInstanceCleanupResult = {
  id: string;
  branch?: string;
  shortName?: string;
  path?: string;
  actions?: string[];
};

export type LauncherBranchInstanceCleanupIssue = {
  id: string;
  code: string;
  message: string;
  branch?: string;
  shortName?: string;
};

export type LauncherBranchInstanceCleanupResponse = {
  ok: boolean;
  cleaned: LauncherBranchInstanceCleanupResult[];
  failed: LauncherBranchInstanceCleanupIssue[];
  skipped: LauncherBranchInstanceCleanupIssue[];
};

export type LauncherBranchInstances = {
  schemaVersion: number;
  integrationRoot: string;
  branchPool: string;
  currentId: string;
  currentShortName?: string;
  currentWorkbenchTitle?: string;
  currentLauncherTitle?: string;
  items: LauncherBranchInstance[];
};

type LauncherBranchInstancePayload = Omit<LauncherBranchInstance, "runtime" | "startable"> & {
  runtime?: LauncherBranchInstanceRuntime;
  startable?: boolean;
};

type LauncherBranchInstancesPayload = Omit<LauncherBranchInstances, "items"> & {
  items: LauncherBranchInstancePayload[];
};

export type LauncherStartupSettingsUpdateResponse = {
  ok: boolean;
  setting: LauncherStartupSettings;
  message: string;
};

function legacyBranchInstanceRuntime(item: LauncherBranchInstancePayload): LauncherBranchInstanceRuntime {
  const observedState = String(item.observedState || "closed").trim().toLowerCase();
  const backendPid = Math.max(0, Number(item.pids?.backend || 0));
  const windowPid = Math.max(0, Number(item.pids?.window || 0));
  const backendAlive = Boolean(item.alive || backendPid > 0);
  const windowOpen = windowPid > 0;
  let lifecycleState: LauncherBranchInstanceRuntime["lifecycleState"] = "closed";
  if (["opening", "starting"].includes(observedState)) {
    lifecycleState = "starting";
  } else if (["restarting", "restart"].includes(observedState)) {
    lifecycleState = "restarting";
  } else if (["closing", "stopping", "force_stopping"].includes(observedState)) {
    lifecycleState = "stopping";
  } else if (["failed", "error"].includes(observedState)) {
    lifecycleState = "error";
  } else if (backendAlive || windowOpen || ["open", "running", "healthy", "partial"].includes(observedState)) {
    // The flat contract cannot prove health, listening, or frontend readiness.
    lifecycleState = "partial";
  }

  const runtime: LauncherBranchInstanceRuntime = {
    lifecycleState,
    desiredState: lifecycleState === "closed" ? "closed" : "open",
    observedState,
    phase: "steady",
    backend: {
      alive: backendAlive,
      healthy: false,
      listening: false,
      port: Math.max(0, Number(item.port || 0)),
      portReserved: Number(item.port || 0) > 0 && !backendAlive,
      portConflict: false,
      pid: backendPid,
    },
    frontend: {
      mode: "bundled_static_dist",
      ready: false,
    },
    window: {
      open: windowOpen,
      pid: windowPid,
      title: String(item.workbenchTitle || item.shortName || item.branch || item.id || ""),
      titleObserved: false,
    },
  };
  if (lifecycleState === "error") {
    runtime.error = {
      code: "legacy_runtime_error",
      message: "The stale Launcher runtime reported a failed branch instance.",
    };
  }
  return runtime;
}

function normalizeLauncherBranchInstances(payload: LauncherBranchInstancesPayload): LauncherBranchInstances {
  return {
    ...payload,
    items: (payload.items || []).map((item) => {
      if (item.runtime) {
        return {
          ...item,
          runtime: item.runtime,
          startable: Boolean(item.startable),
        };
      }
      return {
        ...item,
        runtime: legacyBranchInstanceRuntime(item),
        startable: false,
        startBlockReason: "launcher_refresh_required",
      };
    }),
  };
}

export function launcherEndpoint(path = "") {
  return relativeLauncherEndpoint(path);
}

function relativeLauncherEndpoint(path = "") {
  const suffix = path ? `/${path.replace(/^\/+/, "")}` : "";
  return `${LAUNCHER_ENDPOINT}${suffix}`;
}

async function fetchLauncherJson<T>(path: string, init?: RequestInit): Promise<T> {
  if (launcherIpcBridge() !== null) {
    return invokeLauncherJson<T>(path, init);
  }
  return fetchJson<T>(relativeLauncherEndpoint(path), init);
}

async function invokeLauncherLifecycleJson<T>(path: string, init?: RequestInit): Promise<T> {
  if (launcherIpcBridge() === null) {
    throw new LauncherControlPlaneNotReadyError("Launcher IPC control plane host is not ready.");
  }
  return invokeLauncherJson<T>(path, init);
}

function isLauncherControlConnectionError(error: unknown) {
  if (error instanceof TypeError) {
    return true;
  }
  const message = error instanceof Error ? error.message : String(error || "");
  return /failed to fetch|networkerror|load failed|cors/i.test(message);
}

export function getLauncherStatus() {
  return fetchLauncherJson<LauncherStatus>("status");
}

export function getLauncherBranchInstances(options?: { cleanupMetadata?: boolean }) {
  const path = options?.cleanupMetadata ? "branch-instances?cleanupMetadata=1" : "branch-instances";
  return fetchLauncherJson<LauncherBranchInstancesPayload>(path)
    .then(normalizeLauncherBranchInstances);
}

export function getLocalBranchInstances(options?: { cleanupMetadata?: boolean }) {
  const suffix = options?.cleanupMetadata ? "?cleanupMetadata=1" : "";
  return fetchJson<LauncherBranchInstancesPayload>(`/api/launcher/branch-instances${suffix}`)
    .then(normalizeLauncherBranchInstances);
}

export function requestBranchInstanceLifecycle(
  instanceId: string,
  operation: LauncherOperation,
  trigger?: string,
) {
  const headers = new Headers({ "Content-Type": "application/json" });
  if (trigger) {
    headers.set("X-Vibelution-Launcher-Trigger", trigger);
  }
  return fetchLauncherJson<LauncherControlResponse>(`branch-instances/${operation}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ instanceId }),
  });
}

export function requestBranchInstanceCleanup(instanceIds: string[], confirm: boolean) {
  return fetchLauncherJson<LauncherBranchInstanceCleanupResponse>("branch-instances/cleanup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instanceIds, confirm }),
  });
}

export function startLauncherBundle() {
  return invokeLauncherLifecycleJson<LauncherControlResponse>("start", {
    method: "POST",
  });
}

export function stopLauncherBundle(trigger = "launcher_route_stop_button") {
  return invokeLauncherLifecycleJson<LauncherControlResponse>("stop", {
    method: "POST",
    headers: { "X-Vibelution-Launcher-Trigger": trigger },
  });
}

export function requestWorkbenchWindowCloseOnPageHide(operation: "stop" | "force-stop") {
  const trigger = operation === "force-stop"
    ? "app_shell_window_close_confirmed_active_work"
    : "app_shell_window_close";
  if (launcherIpcBridge() === null) {
    return false;
  }
  try {
    void invokeLauncherJson<LauncherControlResponse>(operation, {
      method: "POST",
      headers: new Headers({ "X-Vibelution-Launcher-Trigger": trigger }),
    }).catch(() => undefined);
    return true;
  } catch {
    return false;
  }
}

export function forceStopLauncherBundle(trigger = "launcher_route_force_stop_button") {
  return invokeLauncherLifecycleJson<LauncherControlResponse>("force-stop", {
    method: "POST",
    headers: { "X-Vibelution-Launcher-Trigger": trigger },
  });
}

export function restartLauncherBundle() {
  return invokeLauncherLifecycleJson<LauncherControlResponse>("restart", {
    method: "POST",
  });
}

export function cancelRuntimeLifecycleCommand(request: RuntimeLifecycleCancelRequest) {
  return fetchJson<RuntimeLifecycleCancelResponse>("/api/runtime/lifecycle-command/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/**
 * Runtime read model shared by route-level polling surfaces.
 * It intentionally bypasses the launcher control-plane proxy because this is
 * served by the workbench backend itself.
 */
export function getRuntimeSummary(signal?: AbortSignal) {
  return fetchJson<RuntimeSummary>("/api/runtime/summary", { signal });
}

export function updateWorkbenchWindowMode(request: WorkbenchWindowModeUpdateRequest) {
  return fetchLauncherJson<WorkbenchWindowModeUpdateResponse>("settings/workbench-window", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function saveLauncherWorkbenchWindowMode(request: WorkbenchWindowModeUpdateRequest) {
  return updateWorkbenchWindowMode(request);
}

export function updateLauncherStartupSettings(setting: LauncherStartupSettings) {
  return fetchLauncherJson<LauncherStartupSettingsUpdateResponse>("settings/startup", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      runtime: {
        profile: setting.runtime.profile,
        preflightDoctor: setting.runtime.preflightDoctor,
        requireVenv: setting.runtime.requireVenv,
      },
      launcher: {
        controlPort: setting.launcher.controlPort,
      },
      workbench: {
        backendPort: setting.workbench.backendPort,
        frontendPort: setting.workbench.frontendPort,
        windowMode: setting.workbench.windowMode,
        windowSize: setting.workbench.windowSize,
      },
      interface: {
        language: setting.interface.language,
      },
      baseHash: setting.configHash,
    }),
  });
}

export function updateLauncherDeveloperMode(request: LauncherDeveloperModeUpdateRequest) {
  return fetchLauncherJson<LauncherDeveloperModeUpdateResponse>("developer-mode", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function resetLauncherDeveloperSandbox() {
  return fetchLauncherJson<LauncherDeveloperModeUpdateResponse>("developer-mode/reset-sandbox", {
    method: "POST",
  });
}

export function getLauncherDeveloperNoiseOverview() {
  return fetchLauncherJson<LauncherDeveloperNoiseOverview>("developer-mode/noise-overview");
}

export function previewLauncherDeveloperCleanup(action: LauncherDeveloperCleanupAction) {
  return fetchLauncherJson<LauncherDeveloperCleanupPreviewResponse>("developer-mode/cleanup/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

export function applyLauncherDeveloperCleanup(request: LauncherDeveloperCleanupApplyRequest) {
  return fetchLauncherJson<LauncherDeveloperCleanupApplyResponse>("developer-mode/cleanup/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function getLauncherMaintenanceSummary() {
  return fetchLauncherJson<LauncherMaintenanceSummary>("maintenance/reset/summary");
}

export function previewLauncherMaintenancePlan(request: LauncherMaintenancePreviewRequest) {
  return fetchLauncherJson<LauncherMaintenancePreviewResponse>("maintenance/reset/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function applyLauncherMaintenancePlan(request: LauncherMaintenanceApplyRequest) {
  return fetchLauncherJson<LauncherMaintenanceApplyResponse>("maintenance/reset/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export type LauncherSupervisorControlResponse = Omit<LauncherControlResponse, "operation"> & {
  operation: "supervisor_reattach";
  blockedReason?: string;
  blockers?: string[];
};

export function reattachLauncherSupervisor() {
  return invokeLauncherLifecycleJson<LauncherSupervisorControlResponse>("supervisor/reattach", {
    method: "POST",
  });
}
