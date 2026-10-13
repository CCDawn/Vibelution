/** Device-local rail preference. Team membership and transcripts remain server-owned. */
const STORAGE_KEY = "vibelution.chat.hiddenTeams.v1";
type VisibilityStorage = Pick<Storage, "getItem" | "setItem">;

export function normalizeHiddenTeamIds(value: unknown): string[] {
  return Array.isArray(value)
    ? [...new Set(value.filter((id): id is string => typeof id === "string").map((id) => id.trim()).filter(Boolean))]
    : [];
}

function defaultStorage(): VisibilityStorage | null {
  try { return typeof localStorage === "undefined" ? null : localStorage; }
  catch { return null; }
}

export function loadHiddenTeamIds(storage: VisibilityStorage | null = defaultStorage()): string[] {
  try { return normalizeHiddenTeamIds(JSON.parse(storage?.getItem(STORAGE_KEY) || "[]")); }
  catch { return []; }
}

export function saveHiddenTeamIds(ids: readonly string[], storage: VisibilityStorage | null = defaultStorage()): void {
  try { storage?.setItem(STORAGE_KEY, JSON.stringify(normalizeHiddenTeamIds(ids))); }
  catch { /* Keep the in-memory preference when browser storage is unavailable. */ }
}
