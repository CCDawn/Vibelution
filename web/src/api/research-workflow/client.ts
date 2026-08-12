import { fetchJson } from "../client";

export { fetchJson };

export function requireText(value: string, field: string): string {
  const normalized = String(value || "").trim();
  if (!normalized) {
    throw new Error(`${field} is required`);
  }
  return normalized;
}

export function requireTeamId(teamId: string): string {
  return requireText(teamId, "teamId");
}

export function teamQuery(teamId: string, extra?: URLSearchParams): string {
  const query = new URLSearchParams();
  query.set("teamId", requireTeamId(teamId));
  extra?.forEach((value, key) => query.append(key, value));
  return `?${query.toString()}`;
}

export const JSON_HEADERS = { "Content-Type": "application/json" } as const;
