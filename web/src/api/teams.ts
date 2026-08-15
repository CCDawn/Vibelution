import { fetchJson } from "./client";
import type { TeamListPayload } from "./types";

export function listTeams(): Promise<TeamListPayload> {
  return fetchJson<TeamListPayload>("/api/teams");
}
