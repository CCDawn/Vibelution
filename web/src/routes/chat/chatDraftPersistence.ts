export const CHAT_DRAFTS_STORAGE_KEY = "vibelution.chat.drafts.v1";
export const CHAT_DRAFTS_MAX_SESSIONS = 20;
export const CHAT_DRAFT_MAX_CHARS = 64 * 1024;
export const CHAT_DRAFT_SAVE_DEBOUNCE_MS = 450;

export type StoredSessionDraftEntry = {
  sessionId: string;
  draft: string;
};

const pendingDraftSaves = new Map<string, string>();
let pendingSaveTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Composer draft persistence: plain-text per-session drafts survive a
 * reload/restart via localStorage. Plain text only (no attachments,
 * references, or composer mode state), bounded to a small LRU window of
 * sessions with a hard per-draft size cap, and written on a debounce so
 * keystroke-rate changes never hit storage synchronously.
 */

function hasLocalStorage() {
  return typeof localStorage !== "undefined" && localStorage !== null;
}

export function clampStoredSessionDraft(draft: string): string {
  const text = String(draft ?? "");
  return text.length > CHAT_DRAFT_MAX_CHARS ? text.slice(0, CHAT_DRAFT_MAX_CHARS) : text;
}

/** Newest entry last; drops empty drafts and older overflow beyond the LRU cap. */
export function upsertStoredSessionDraft(
  entries: StoredSessionDraftEntry[],
  sessionId: string,
  draft: string,
): StoredSessionDraftEntry[] {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return entries;
  }
  const clamped = clampStoredSessionDraft(draft);
  const remaining = entries.filter((entry) => entry.sessionId !== normalizedSessionId);
  if (!clamped) {
    return remaining;
  }
  return capStoredSessionDrafts([...remaining, { sessionId: normalizedSessionId, draft: clamped }]);
}

export function capStoredSessionDrafts(
  entries: StoredSessionDraftEntry[],
): StoredSessionDraftEntry[] {
  const capped = entries.filter((entry) => entry.draft);
  return capped.length > CHAT_DRAFTS_MAX_SESSIONS
    ? capped.slice(capped.length - CHAT_DRAFTS_MAX_SESSIONS)
    : capped;
}

export function removeSessionDraftEntry(
  entries: StoredSessionDraftEntry[],
  sessionId: string,
): StoredSessionDraftEntry[] {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return entries;
  }
  return entries.filter((entry) => entry.sessionId !== normalizedSessionId);
}

function readStoredSessionDraftEntries(): StoredSessionDraftEntry[] {
  if (!hasLocalStorage()) {
    return [];
  }
  try {
    const raw = localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    const entries: StoredSessionDraftEntry[] = [];
    for (const item of parsed) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const sessionId = String((item as { sessionId?: unknown }).sessionId ?? "");
      const draft = String((item as { draft?: unknown }).draft ?? "");
      if (sessionId.trim() && draft) {
        entries.push({ sessionId, draft });
      }
    }
    return capStoredSessionDrafts(entries);
  } catch {
    // Corrupted storage must never break composer startup.
    return [];
  }
}

function writeStoredSessionDraftEntries(entries: StoredSessionDraftEntry[]) {
  if (!hasLocalStorage()) {
    return;
  }
  try {
    localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, JSON.stringify(capStoredSessionDrafts(entries)));
  } catch {
    // Quota/privacy failures are non-fatal: in-memory drafts keep working.
  }
}

function flushPendingSessionDraftSaves() {
  if (pendingSaveTimer !== null) {
    clearTimeout(pendingSaveTimer);
    pendingSaveTimer = null;
  }
  if (!pendingDraftSaves.size) {
    return;
  }
  let entries = readStoredSessionDraftEntries();
  for (const [sessionId, draft] of pendingDraftSaves) {
    entries = upsertStoredSessionDraft(entries, sessionId, draft);
  }
  pendingDraftSaves.clear();
  writeStoredSessionDraftEntries(entries);
}

/** Debounced save: coalesces keystroke bursts into one storage write. */
export function scheduleSessionDraftSave(sessionId: string, draft: string) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return;
  }
  pendingDraftSaves.set(normalizedSessionId, String(draft ?? ""));
  if (pendingSaveTimer !== null) {
    return;
  }
  pendingSaveTimer = setTimeout(() => {
    pendingSaveTimer = null;
    flushPendingSessionDraftSaves();
  }, CHAT_DRAFT_SAVE_DEBOUNCE_MS);
}

/** Immediate removal: a submitted/closed session draft must never resurrect. */
export function removeStoredSessionDraft(sessionId: string) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return;
  }
  pendingDraftSaves.delete(normalizedSessionId);
  writeStoredSessionDraftEntries(
    removeSessionDraftEntry(readStoredSessionDraftEntries(), normalizedSessionId),
  );
}

/** Startup hydration for the workbench in-memory draft map. */
export function readStoredSessionDrafts(): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const entry of readStoredSessionDraftEntries()) {
    drafts[entry.sessionId] = entry.draft;
  }
  return drafts;
}

/** Test hooks: force pending debounced writes and reset module state. */
export function flushPendingSessionDraftWrites() {
  flushPendingSessionDraftSaves();
}

export function resetChatDraftPersistenceForTests() {
  if (pendingSaveTimer !== null) {
    clearTimeout(pendingSaveTimer);
    pendingSaveTimer = null;
  }
  pendingDraftSaves.clear();
}
