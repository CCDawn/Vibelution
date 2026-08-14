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
  return { launcherInvoke };
}

export function hasLauncherIpcBridge() {
  return launcherIpcBridge() !== null;
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

export function getLauncherBranchInstances() {
  return fetchLauncherJson<LauncherBranchInstancesPayload>("branch-instances")
    .then(normalizeLauncherBranchInstances);
}

export function getLocalBranchInstances() {
  return fetchJson<LauncherBranchInstancesPayload>("/api/launcher/branch-instances")
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
  return fetchLauncherJson<LauncherControlResponse>("start", {
    method: "POST",
  });
}

export function stopLauncherBundle(trigger = "launcher_route_stop_button") {
  return fetchLauncherJson<LauncherControlResponse>("stop", {
    method: "POST",
    headers: { "X-Vibelution-Launcher-Trigger": trigger },
  });
}

export function requestWorkbenchWindowCloseOnPageHide(operation: "stop" | "force-stop") {
  const trigger = operation === "force-stop"
    ? "app_shell_window_close_confirmed_active_work"
    : "app_shell_window_close";
  try {
    const request = globalThis.fetch(relativeLauncherEndpoint(operation), {
      method: "POST",
      credentials: "same-origin",
      headers: new Headers({ "X-Vibelution-Launcher-Trigger": trigger }),
      keepalive: true,
    });
    void request.catch(() => undefined);
    return true;
  } catch {
    return false;
  }
}

export function forceStopLauncherBundle(trigger = "launcher_route_force_stop_button") {
  return fetchLauncherJson<LauncherControlResponse>("force-stop", {
    method: "POST",
    headers: { "X-Vibelution-Launcher-Trigger": trigger },
  });
}

export function restartLauncherBundle() {
  return fetchLauncherJson<LauncherControlResponse>("restart", {
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
  return fetchLauncherJson<LauncherSupervisorControlResponse>("supervisor/reattach", {
    method: "POST",
  });
}
