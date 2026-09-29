export const TOOL_EXPAND_STORAGE_KEY = "vibelution.chat.toolExpand.v1";
export const TOOL_EXPAND_MAX_ENTRIES = 512;

export type StoredToolExpandEntry = {
  sessionId: string;
  key: string;
};

/**
 * Tool-row expand persistence: the user's explicit expand choices survive a
 * reload/restart via localStorage, scoped per session (mirrors the robustness
 * style of routes/chat/chatDraftPersistence.ts). Only OPEN rows are stored —
 * collapsed is the default, so a collapse is a removal, not a write. Bounded
 * to an LRU window of entries with silent reset on corrupted storage; storage
 * failures never break the row UI.
 */

function hasLocalStorage() {
  return typeof localStorage !== "undefined" && localStorage !== null;
}

function normalizeScope(value: unknown): string {
  return String(value ?? "").trim();
}

function entryIdentity(entry: StoredToolExpandEntry): string {
  return `${entry.sessionId}\u0000${entry.key}`;
}

/**
 * Dedupe by (sessionId, key) keeping the LAST occurrence (LRU touch), drop
 * invalid rows, and keep only the newest `TOOL_EXPAND_MAX_ENTRIES` entries.
 */
export function capToolExpandEntries(
  entries: StoredToolExpandEntry[],
): StoredToolExpandEntry[] {
  const deduped = new Map<string, StoredToolExpandEntry>();
  for (const entry of entries) {
    if (!entry || normalizeScope(entry.sessionId) === "" || normalizeScope(entry.key) === "") {
      continue;
    }
    const normalized: StoredToolExpandEntry = {
      sessionId: normalizeScope(entry.sessionId),
      key: normalizeScope(entry.key),
    };
    deduped.set(entryIdentity(normalized), normalized);
  }
  const list = [...deduped.values()];
  return list.length > TOOL_EXPAND_MAX_ENTRIES
    ? list.slice(list.length - TOOL_EXPAND_MAX_ENTRIES)
    : list;
}

/** Remove then append: the touched entry becomes the newest (LRU). */
export function upsertToolExpandEntry(
  entries: StoredToolExpandEntry[],
  sessionId: string,
  key: string,
): StoredToolExpandEntry[] {
  const normalizedSessionId = normalizeScope(sessionId);
  const normalizedKey = normalizeScope(key);
  if (!normalizedSessionId || !normalizedKey) {
    return entries;
  }
  const identity = entryIdentity({ sessionId: normalizedSessionId, key: normalizedKey });
  return capToolExpandEntries([
    ...entries.filter((entry) => entryIdentity(entry) !== identity),
    { sessionId: normalizedSessionId, key: normalizedKey },
  ]);
}

export function removeToolExpandEntry(
  entries: StoredToolExpandEntry[],
  sessionId: string,
  key: string,
): StoredToolExpandEntry[] {
  const normalizedSessionId = normalizeScope(sessionId);
  const normalizedKey = normalizeScope(key);
  if (!normalizedSessionId || !normalizedKey) {
    return entries;
  }
  const identity = entryIdentity({ sessionId: normalizedSessionId, key: normalizedKey });
  return entries.filter((entry) => entryIdentity(entry) !== identity);
}

export function openToolKeysForEntries(
  entries: StoredToolExpandEntry[],
  sessionId: string,
): Set<string> {
  const normalizedSessionId = normalizeScope(sessionId);
  const keys = new Set<string>();
  if (!normalizedSessionId) {
    return keys;
  }
  for (const entry of entries) {
    if (entry.sessionId === normalizedSessionId) {
      keys.add(entry.key);
    }
  }
  return keys;
}

// Module cache: expand state must be readable synchronously on mount
// (useState initializer), and repeated mounts re-read without re-parsing.
let cachedEntries: StoredToolExpandEntry[] | null = null;

function readStoredEntries(): StoredToolExpandEntry[] {
  if (cachedEntries) {
    return cachedEntries;
  }
  if (!hasLocalStorage()) {
    return [];
  }
  try {
    const raw = localStorage.getItem(TOOL_EXPAND_STORAGE_KEY);
    if (!raw) {
      cachedEntries = [];
      return cachedEntries;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      // Corrupted shape: silently reset instead of breaking row startup.
      cachedEntries = [];
      return cachedEntries;
    }
    const entries: StoredToolExpandEntry[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const sessionId = normalizeScope((item as { sessionId?: unknown }).sessionId);
      const key = normalizeScope((item as { key?: unknown }).key);
      if (sessionId && key) {
        entries.push({ sessionId, key });
      }
    }
    cachedEntries = capToolExpandEntries(entries);
    return cachedEntries;
  } catch {
    // Corrupted JSON must never break tool-row startup.
    cachedEntries = [];
    return cachedEntries;
  }
}

function writeStoredEntries(entries: StoredToolExpandEntry[]) {
  cachedEntries = entries;
  if (!hasLocalStorage()) {
    return;
  }
  try {
    localStorage.setItem(TOOL_EXPAND_STORAGE_KEY, JSON.stringify(capToolExpandEntries(entries)));
  } catch {
    // Quota/privacy failures are non-fatal: the row keeps working in memory.
  }
}

/** Open tool-row keys for one session (empty set without a session scope). */
export function readOpenToolKeys(sessionId: string): Set<string> {
  return openToolKeysForEntries(readStoredEntries(), sessionId);
}

/** Record one user expand/collapse choice; collapses free their entry. */
export function setToolRowOpen(sessionId: string, key: string, open: boolean) {
  const normalizedSessionId = normalizeScope(sessionId);
  const normalizedKey = normalizeScope(key);
  if (!normalizedSessionId || !normalizedKey) {
    return;
  }
  if (open) {
    writeStoredEntries(upsertToolExpandEntry(readStoredEntries(), normalizedSessionId, normalizedKey));
    return;
  }
  writeStoredEntries(removeToolExpandEntry(readStoredEntries(), normalizedSessionId, normalizedKey));
}

/** Test hook: drop the module cache so a test file starts from clean storage. */
export function resetToolExpandPersistenceForTests() {
  cachedEntries = null;
}
