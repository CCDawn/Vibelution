import { fetchJson } from "./client";
import type {
  AiSearchRun,
  AiSearchRunListPayload,
  Team,
  TeamListPayload,
  TeamOrganizationCanvas,
} from "./types";

function writeJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  return fetchJson<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

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

export function createTeam(body: {
  name?: string;
  description?: string;
  purpose?: string;
  members?: unknown[];
}): Promise<Team> {
  return writeJson<Team>("/api/teams", "POST", body);
}

export function updateTeam(
  teamId: string,
  body: {
    name?: string | null;
    description?: string | null;
    purpose?: string | null;
    status?: string | null;
    members?: unknown[] | null;
  },
): Promise<Team> {
  return writeJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`, "PATCH", body);
}

export function archiveTeam(teamId: string): Promise<Team> {
  return writeJson<Team>(`/api/teams/${encodeURIComponent(teamId)}`, "DELETE");
}

export function saveTeamCanvas(canvas: TeamOrganizationCanvas): Promise<TeamOrganizationCanvas> {
  return writeJson<TeamOrganizationCanvas>(
    `/api/teams/${encodeURIComponent(canvas.teamId)}/canvas`,
    "PUT",
    canvas,
  );
}

export function startAiSearchRun(
  teamId: string,
  body: {
    topic: string;
    sourceLimit?: number;
    maxResultsPerQuery?: number;
    includeSignals?: boolean;
  },
): Promise<AiSearchRun> {
  return writeJson<AiSearchRun>(`/api/teams/${encodeURIComponent(teamId)}/ai-search-runs`, "POST", body);
}

export function syncTeamChatRoom(teamId: string): Promise<Team> {
  return writeJson<Team>(`/api/teams/${encodeURIComponent(teamId)}/chat-room/sync`, "POST");
}

export type TeamRepairResult = {
  team?: Team;
  teamId?: string;
};

export function repairChallengeCupTeamAgents(teamId: string): Promise<TeamRepairResult> {
  return writeJson<TeamRepairResult>(
    `/api/teams/${encodeURIComponent(teamId)}/challenge-cup-agents/repair`,
    "POST",
  );
}

export function repairKnowledgeExpansionTeamAgents(teamId: string): Promise<TeamRepairResult> {
  return writeJson<TeamRepairResult>(
    `/api/teams/${encodeURIComponent(teamId)}/knowledge-expansion-agents/repair`,
    "POST",
  );
}
