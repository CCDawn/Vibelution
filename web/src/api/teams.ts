import { fetchJson } from "./client";
import type {
  AiSearchRunListPayload,
  Team,
  TeamListPayload,
  TeamOrganizationCanvas,
} from "./types";

export function listTeams(options?: {
  signal?: AbortSignal;
  includeArchived?: boolean;
}): Promise<TeamListPayload> {
  const search = new URLSearchParams();
  if (options?.includeArchived) {
    search.set("includeArchived", "true");
  }
  const suffix = search.toString();
  return fetchJson<TeamListPayload>(suffix ? `/api/teams?${suffix}` : "/api/teams", {
    signal: options?.signal,
  });
}

export function fetchTeam(
  teamId: string,
  options?: { signal?: AbortSignal; detail?: string },
): Promise<Team> {
  const search = new URLSearchParams();
  if (options?.detail) {
    search.set("detail", options.detail);
  }
  const suffix = search.toString();
  const path = `/api/teams/${encodeURIComponent(teamId)}`;
  return fetchJson<Team>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}

export function fetchTeamCanvas(
  teamId: string,
  options?: { signal?: AbortSignal },
): Promise<TeamOrganizationCanvas> {
  return fetchJson<TeamOrganizationCanvas>(
    `/api/teams/${encodeURIComponent(teamId)}/canvas`,
    { signal: options?.signal },
  );
}

export function listTeamAiSearchRuns(
  teamId: string,
  options?: { signal?: AbortSignal; limit?: number },
): Promise<AiSearchRunListPayload> {
  const search = new URLSearchParams();
  if (options?.limit != null) {
    search.set("limit", String(options.limit));
  }
  const suffix = search.toString();
  const path = `/api/teams/${encodeURIComponent(teamId)}/ai-search-runs`;
  return fetchJson<AiSearchRunListPayload>(suffix ? `${path}?${suffix}` : path, {
    signal: options?.signal,
  });
}
