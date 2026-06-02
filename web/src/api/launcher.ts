import { fetchJson } from "./client";
import type { LauncherControlResponse, LauncherStatus } from "./types";

export const LAUNCHER_ENDPOINT = "/api/launcher";

export function launcherRestartEndpoint(confirmedActiveWork = false) {
  return confirmedActiveWork ? `${LAUNCHER_ENDPOINT}/restart?confirmedActiveWork=true` : `${LAUNCHER_ENDPOINT}/restart`;
}

export function getLauncherStatus() {
  return fetchJson<LauncherStatus>(`${LAUNCHER_ENDPOINT}/status`);
}

export function startLauncherBundle() {
  return fetchJson<LauncherControlResponse>(`${LAUNCHER_ENDPOINT}/start`, {
    method: "POST",
  });
}

export function stopLauncherBundle() {
  return fetchJson<LauncherControlResponse>(`${LAUNCHER_ENDPOINT}/stop`, {
    method: "POST",
  });
}

export function restartLauncherBundle(confirmedActiveWork = false) {
  return fetchJson<LauncherControlResponse>(launcherRestartEndpoint(confirmedActiveWork), {
    method: "POST",
  });
}
