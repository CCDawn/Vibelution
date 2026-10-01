/**
 * Session list display preferences (sort + timeline grouping), persisted in
 * localStorage. Kept separate from the query hook so tests can exercise the
 * pure normalization and the storage round-trip independently.
 */

export type SessionListSortBy = "updatedAt" | "createdAt";

export type SessionListPreferences = {
  sortBy: SessionListSortBy;
  /** Group the loaded session page by day boundary (today/yesterday/…). */
  timelineGrouping: boolean;
};

export const DEFAULT_SESSION_LIST_PREFERENCES: SessionListPreferences = {
  sortBy: "updatedAt",
  timelineGrouping: false,
};

const SESSION_LIST_PREFERENCES_STORAGE_KEY = "vibelution.sessionList.preferences.v1";

/** Backend sort value for the session index query. */
export function sessionListSortQueryValue(sortBy: SessionListSortBy): string {
  return sortBy === "createdAt" ? "createdAt_desc" : "updatedAt_desc";
}

export function normalizeSessionListSortBy(value: unknown): SessionListSortBy {
  return value === "createdAt" ? "createdAt" : "updatedAt";
}

export function normalizeSessionListPreferences(value: unknown): SessionListPreferences {
  if (!value || typeof value !== "object") {
    return { ...DEFAULT_SESSION_LIST_PREFERENCES };
  }
  const raw = value as Record<string, unknown>;
  return {
    sortBy: normalizeSessionListSortBy(raw.sortBy),
    timelineGrouping: raw.timelineGrouping === true,
  };
}

type SessionListStorage = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): SessionListStorage | null {
  try {
    if (typeof localStorage === "undefined") {
      return null;
    }
    return localStorage;
  } catch {
    return null;
  }
}

export function loadSessionListPreferences(
  storage: SessionListStorage | null = defaultStorage(),
): SessionListPreferences {
  if (!storage) {
    return { ...DEFAULT_SESSION_LIST_PREFERENCES };
  }
  try {
    const raw = storage.getItem(SESSION_LIST_PREFERENCES_STORAGE_KEY);
    if (!raw) {
      return { ...DEFAULT_SESSION_LIST_PREFERENCES };
    }
    return normalizeSessionListPreferences(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_SESSION_LIST_PREFERENCES };
  }
}

export function saveSessionListPreferences(
  preferences: SessionListPreferences,
  storage: SessionListStorage | null = defaultStorage(),
): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(
      SESSION_LIST_PREFERENCES_STORAGE_KEY,
      JSON.stringify(normalizeSessionListPreferences(preferences)),
    );
  } catch {
    // Persistence is best-effort; the in-memory preference still applies.
  }
}
