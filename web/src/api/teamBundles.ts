import { fetchJson } from "./client";
import type { TeamBundle, TeamBundleImportReport } from "./types";

function postTeamBundleJson<T>(url: string, body: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
}

export function fetchTeamBundle(teamId: string): Promise<TeamBundle> {
  return fetchJson<TeamBundle>(`/api/teams/${encodeURIComponent(teamId)}/bundle`);
}

export function importTeamBundle(
  bundle: TeamBundle,
  options?: { dryRun?: boolean; confirm?: boolean },
): Promise<TeamBundleImportReport> {
  return postTeamBundleJson<TeamBundleImportReport>("/api/team-bundles/import", {
    bundle,
    dryRun: options?.dryRun ?? true,
    confirm: options?.confirm ?? false,
  });
}
