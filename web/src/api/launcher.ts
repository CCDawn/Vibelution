import { fetchJson } from "./client";
import type { LauncherControlResponse, LauncherStatus } from "./types";

export const LAUNCHER_ENDPOINT = "/api/launcher";
export const DEFAULT_LAUNCHER_CONTROL_PORT = 8765;

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

export function stopLauncherBundle() {
  return fetchLauncherJson<LauncherControlResponse>("stop", {
    method: "POST",
  });
}

export function restartLauncherBundle() {
  return fetchLauncherJson<LauncherControlResponse>("restart", {
    method: "POST",
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
