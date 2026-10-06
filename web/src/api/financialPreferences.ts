import { fetchJson } from "./client";
import type { FinancialPreference, FinancialPreferences } from "./types/financialPreferences";
import type { FinancialWorkspacePatch, FinancialWorkspaceSettings } from "./types/financialPreferences";
export type { FinancialPreference, FinancialPreferences } from "./types/financialPreferences";
export type { FinancialWatchStock, FinancialResearchProfile, FinancialManualPosition, FinancialReviewCase, FinancialWorkspacePatch, FinancialWorkspaceSettings } from "./types/financialPreferences";

export const financialWorkspaceKey = (agentId: string) => ["finance", "workspace-settings", agentId] as const;
export function fetchFinancialWorkspace(agentId: string, options?: { signal?: AbortSignal }): Promise<FinancialWorkspaceSettings> {
  return fetchJson(`/api/financial-preferences/${encodeURIComponent(agentId)}/workspace`, { signal: options?.signal });
}
export function updateFinancialWorkspace(agentId: string, expectedRevision: number, patch: FinancialWorkspacePatch): Promise<FinancialWorkspaceSettings> {
  return fetchJson(`/api/financial-preferences/${encodeURIComponent(agentId)}/workspace`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ expectedRevision, patch }) });
}

export const financialPreferenceKeys = { agent: (agentId: string) => ["finance", "preferences", agentId] as const };
export function fetchFinancialPreferences(agentId: string, options?: { signal?: AbortSignal }): Promise<FinancialPreferences> {
  return fetchJson(`/api/financial-preferences/${encodeURIComponent(agentId)}`, { signal: options?.signal });
}
export function saveFinancialPreference(agentId: string, text: string, clientRequestId: string): Promise<FinancialPreference> {
  return fetchJson(`/api/financial-preferences/${encodeURIComponent(agentId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, clientRequestId }) });
}
export function removeFinancialPreference(agentId: string, id: string): Promise<{ id: string; removed: boolean }> {
  return fetchJson(`/api/financial-preferences/${encodeURIComponent(agentId)}/${encodeURIComponent(id)}`, { method: "DELETE" });
}
