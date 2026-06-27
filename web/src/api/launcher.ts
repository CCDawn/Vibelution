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
  LauncherStartupSettings as BaseLauncherStartupSettings,
  LauncherStatus as BaseLauncherStatus,
  RuntimeLifecycleCancelRequest,
  RuntimeLifecycleCancelResponse,
  WorkbenchWindowModeSetting,
  WorkbenchWindowModeUpdateRequest,
  WorkbenchWindowModeUpdateResponse,
} from "./types";

export const LAUNCHER_ENDPOINT = "/api/launcher";
export const DEFAULT_LAUNCHER_CONTROL_PORT = 8765;

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

export type LauncherStartupSettingsUpdateResponse = {
  ok: boolean;
  setting: LauncherStartupSettings;
  message: string;
};

let cachedLauncherControlOrigin = "";

function isLoopbackHost(hostname: string) {
  const host = String(hostname || "").trim().toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function launcherControlOrigin() {
  if (typeof window === "undefined") {
    return "";
  }
  try {
    const current = new URL(window.location.href);
    if (!isLoopbackHost(current.hostname)) {
      return "";
    }
    const currentPort = current.port || (current.protocol === "https:" ? "443" : "80");
    if (currentPort === String(DEFAULT_LAUNCHER_CONTROL_PORT)) {
      return "";
    }
    if (cachedLauncherControlOrigin && cachedLauncherControlOrigin !== current.origin) {
      return cachedLauncherControlOrigin;
    }
    return `${current.protocol}//127.0.0.1:${DEFAULT_LAUNCHER_CONTROL_PORT}`;
  } catch {
    return "";
  }
}

export function launcherEndpoint(path = "") {
  return `${launcherControlOrigin()}${relativeLauncherEndpoint(path)}`;
}

function relativeLauncherEndpoint(path = "") {
  const suffix = path ? `/${path.replace(/^\/+/, "")}` : "";
  return `${LAUNCHER_ENDPOINT}${suffix}`;
}

async function fetchLauncherJson<T>(path: string, init?: RequestInit): Promise<T> {
  const endpoint = launcherEndpoint(path);
  try {
    const payload = await fetchJson<T>(endpoint, init);
    rememberLauncherControlOrigin(payload);
    return payload;
  } catch (error) {
    if (!endpoint.startsWith("http") || !isLauncherControlConnectionError(error)) {
      throw error;
    }
    const payload = await fetchJson<T>(relativeLauncherEndpoint(path), init);
    rememberLauncherControlOrigin(payload);
    return payload;
  }
}

function isLauncherControlConnectionError(error: unknown) {
  if (error instanceof TypeError) {
    return true;
  }
  const message = error instanceof Error ? error.message : String(error || "");
  return /failed to fetch|networkerror|load failed|cors/i.test(message);
}

function rememberLauncherControlOrigin(payload: unknown) {
  if (!payload || typeof payload !== "object") {
    return;
  }
  const status = payload as LauncherStatus;
  const url = status.launcher?.controlPlane?.url;
  if (typeof url !== "string" || !url.trim()) {
    return;
  }
  try {
    const parsed = new URL(url);
    if (isLoopbackHost(parsed.hostname)) {
      cachedLauncherControlOrigin = parsed.origin;
    }
  } catch {
    return;
  }
}

export function resetLauncherControlOriginForTests() {
  cachedLauncherControlOrigin = "";
}

export function launcherRestartEndpoint() {
  return launcherEndpoint("restart");
}

export function getLauncherStatus() {
  return fetchLauncherJson<LauncherStatus>("status");
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
