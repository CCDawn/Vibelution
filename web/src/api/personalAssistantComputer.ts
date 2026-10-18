import { fetchJson } from "./client";
import type { ComputerControlAction, ComputerState, ComputerWindow } from "./types/personalAssistantComputer";

export function fetchPersonalAssistantComputer(options?: { signal?: AbortSignal }): Promise<ComputerState> {
  return fetchJson("/api/personal-assistant/computer", { signal: options?.signal });
}

/** Enumerates windows only on an explicit visit to the computer panel or refresh. */
export function fetchPersonalAssistantComputerWindows(options?: { signal?: AbortSignal }): Promise<{ windows: ComputerWindow[] }> {
  return fetchJson("/api/personal-assistant/computer/windows", { signal: options?.signal });
}

export function grantPersonalAssistantComputer(payload: { selectionId: string; allowVision: true }): Promise<ComputerState> {
  return fetchJson("/api/personal-assistant/computer/grant", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

export function controlPersonalAssistantComputer(payload: { grantId: string; action: ComputerControlAction }): Promise<ComputerState> {
  return fetchJson("/api/personal-assistant/computer/control", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}

export function confirmPersonalAssistantComputer(payload: { grantId: string; pendingId: string; approved: boolean }): Promise<ComputerState> {
  return fetchJson("/api/personal-assistant/computer/confirm", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
  });
}
