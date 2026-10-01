import type { SessionModelSelection, SessionReferenceAttachment } from "../../api/types";

export const CHAT_DRAFTS_STORAGE_KEY = "vibelution.chat.drafts.v1";
export const CHAT_DRAFTS_MAX_SESSIONS = 50;
export const CHAT_DRAFT_MAX_CHARS = 64 * 1024;
export const CHAT_DRAFT_MAX_REFERENCES = 8;
export const CHAT_DRAFT_SAVE_DEBOUNCE_MS = 450;

/**
 * Text-only reference metadata persisted with a draft (ZCode parity ruling:
 * images/files never enter the draft store — `SessionReferenceAttachment` is
 * already pure metadata, so the chip list round-trips verbatim; the persisted
 * shape is a strict allow-list so untrusted storage cannot smuggle fields in).
 */
export type StoredSessionDraftReference = Pick<
  SessionReferenceAttachment,
  | "referenceId"
  | "kind"
  | "sessionId"
  | "title"
  | "agentId"
  | "agentCode"
  | "agentDisplayName"
  | "summary"
  | "createdAt"
  | "knowledgeItemId"
  | "knowledgeBaseId"
  | "artifactId"
  | "filename"
  | "sourceSessionId"
  | "sourceMessageId"
  | "quote"
>;

/** Rich per-session composer state that survives a reload next to the text. */
export type StoredSessionDraftMeta = {
  turnModelSelection?: SessionModelSelection | null;
  referenceAttachments?: StoredSessionDraftReference[];
};

export type StoredSessionDraftEntry = {
  sessionId: string;
  draft: string;
  turnModelSelection?: SessionModelSelection | null;
  referenceAttachments?: StoredSessionDraftReference[];
};

export type StoredSessionDraftState = {
  drafts: Record<string, string>;
  turnModelSelections: Record<string, SessionModelSelection | null>;
  referenceAttachments: Record<string, SessionReferenceAttachment[]>;
};

const REFERENCE_TEXT_FIELDS = [
  "referenceId",
  "kind",
  "sessionId",
  "title",
  "agentId",
  "agentCode",
  "agentDisplayName",
  "summary",
  "createdAt",
  "knowledgeItemId",
  "knowledgeBaseId",
  "artifactId",
  "filename",
  "sourceSessionId",
  "sourceMessageId",
  "quote",
] as const;

/** Fields that actually identify a reference; display-only text does not count. */
const REFERENCE_IDENTITY_FIELDS = [
  "referenceId",
  "sessionId",
  "knowledgeItemId",
  "knowledgeBaseId",
  "artifactId",
  "filename",
  "sourceSessionId",
  "sourceMessageId",
] as const;

const pendingDraftSaves = new Map<string, string>();
const pendingDraftMetas = new Map<string, StoredSessionDraftMeta>();
let pendingSaveTimer: ReturnType<typeof setTimeout> | null = null;

/**
 * Composer draft persistence: per-session drafts survive a reload/restart via
 * localStorage. Plain text plus rich fields (the session's per-turn model
 * selection and its reference chips — never image/file attachments), bounded
 * to a small LRU window of sessions with a hard per-draft size cap, written on
 * a debounce so keystroke-rate changes never hit storage synchronously.
 */

function hasLocalStorage() {
  return typeof localStorage !== "undefined" && localStorage !== null;
}

export function clampStoredSessionDraft(draft: string): string {
  const text = String(draft ?? "");
  return text.length > CHAT_DRAFT_MAX_CHARS ? text.slice(0, CHAT_DRAFT_MAX_CHARS) : text;
}

function textOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

/** Allow-list projection of an (untrusted) reference-like object. */
export function sanitizeStoredDraftReference(value: unknown): StoredSessionDraftReference | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const kind = textOrUndefined(record.kind) ?? "session";
  const sanitized: StoredSessionDraftReference = { kind };
  let hasIdentity = false;
  for (const field of REFERENCE_TEXT_FIELDS) {
    if (field === "kind") {
      continue;
    }
    const text = textOrUndefined(record[field]);
    if (text) {
      sanitized[field] = text;
    }
  }
  // A chip with no identity at all (title-only decoration) cannot be restored
  // meaningfully and is dropped instead of resurrecting as a dead chip.
  for (const field of REFERENCE_IDENTITY_FIELDS) {
    if (sanitized[field]) {
      hasIdentity = true;
      break;
    }
  }
  return hasIdentity ? sanitized : null;
}

export function sanitizeStoredDraftReferences(value: unknown): StoredSessionDraftReference[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const sanitized: StoredSessionDraftReference[] = [];
  for (const item of value) {
    const reference = sanitizeStoredDraftReference(item);
    if (reference) {
      sanitized.push(reference);
    }
    if (sanitized.length >= CHAT_DRAFT_MAX_REFERENCES) {
      break;
    }
  }
  return sanitized;
}

export function sanitizeStoredDraftMeta(value: unknown): StoredSessionDraftMeta {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const record = value as Record<string, unknown>;
  const meta: StoredSessionDraftMeta = {};
  const selection = record.turnModelSelection;
  if (selection && typeof selection === "object" && !Array.isArray(selection)) {
    const modelId = textOrUndefined((selection as Record<string, unknown>).modelId);
    if (modelId) {
      const reasoningEffort = textOrUndefined((selection as Record<string, unknown>).reasoningEffort);
      meta.turnModelSelection = reasoningEffort ? { modelId, reasoningEffort } : { modelId };
    } else if ((selection as Record<string, unknown>).modelId === null) {
      meta.turnModelSelection = null;
    }
  }
  if ("referenceAttachments" in record) {
    meta.referenceAttachments = sanitizeStoredDraftReferences(record.referenceAttachments);
  }
  return meta;
}

function entryHasContent(entry: StoredSessionDraftEntry): boolean {
  return Boolean(entry.draft) || Boolean(entry.referenceAttachments?.length);
}

function mergeEntryMeta(entry: StoredSessionDraftEntry, meta: StoredSessionDraftMeta): StoredSessionDraftEntry {
  const merged: StoredSessionDraftEntry = { ...entry };
  if ("turnModelSelection" in meta) {
    merged.turnModelSelection = meta.turnModelSelection;
  }
  if ("referenceAttachments" in meta) {
    merged.referenceAttachments = meta.referenceAttachments;
  }
  return merged;
}

/** Newest entry last; drops empty drafts and older overflow beyond the LRU cap. */
export function upsertStoredSessionDraft(
  entries: StoredSessionDraftEntry[],
  sessionId: string,
  draft: string,
  meta?: StoredSessionDraftMeta,
): StoredSessionDraftEntry[] {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return entries;
  }
  const existing = entries.find((entry) => entry.sessionId === normalizedSessionId);
  const clamped = clampStoredSessionDraft(draft);
  if (clamped === "" && !meta) {
    // Legacy text-only removal path: an empty draft without meta intent drops
    // the entry, but its stored meta stays untouched for a later meta save.
    if (existing?.referenceAttachments?.length) {
      return capStoredSessionDrafts([
        ...entries.filter((entry) => entry.sessionId !== normalizedSessionId),
        { ...existing, draft: "" },
      ]);
    }
    return entries.filter((entry) => entry.sessionId !== normalizedSessionId);
  }
  const base: StoredSessionDraftEntry = {
    sessionId: normalizedSessionId,
    draft: clamped,
    turnModelSelection: existing?.turnModelSelection,
    referenceAttachments: existing?.referenceAttachments,
  };
  return capStoredSessionDrafts([
    ...entries.filter((entry) => entry.sessionId !== normalizedSessionId),
    meta ? mergeEntryMeta(base, meta) : base,
  ]);
}

/** Merge-only meta upsert: keeps the draft text, replaces the provided fields. */
export function upsertStoredSessionDraftMeta(
  entries: StoredSessionDraftEntry[],
  sessionId: string,
  meta: StoredSessionDraftMeta,
): StoredSessionDraftEntry[] {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return entries;
  }
  const existing = entries.find((entry) => entry.sessionId === normalizedSessionId);
  const base: StoredSessionDraftEntry = existing ?? {
    sessionId: normalizedSessionId,
    draft: "",
  };
  const merged = mergeEntryMeta(base, meta);
  if (!entryHasContent(merged)) {
    return entries.filter((entry) => entry.sessionId !== normalizedSessionId);
  }
  return capStoredSessionDrafts([
    ...entries.filter((entry) => entry.sessionId !== normalizedSessionId),
    merged,
  ]);
}

export function capStoredSessionDrafts(
  entries: StoredSessionDraftEntry[],
): StoredSessionDraftEntry[] {
  const capped = entries.filter(entryHasContent);
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
      const record = item as Record<string, unknown>;
      const sessionId = String(record.sessionId ?? "");
      const draft = String(record.draft ?? "");
      if (!sessionId.trim() || (!draft && record.referenceAttachments === undefined && record.turnModelSelection === undefined)) {
        continue;
      }
      // Old plain-text entries ({sessionId, draft}) read back unchanged — the
      // rich fields simply stay absent; no write-back migration is needed.
      const meta = sanitizeStoredDraftMeta({
        turnModelSelection: record.turnModelSelection,
        referenceAttachments: record.referenceAttachments,
      });
      entries.push({
        sessionId,
        draft,
        ...(meta.turnModelSelection !== undefined ? { turnModelSelection: meta.turnModelSelection } : {}),
        ...(meta.referenceAttachments !== undefined ? { referenceAttachments: meta.referenceAttachments } : {}),
      });
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
  if (!pendingDraftSaves.size && !pendingDraftMetas.size) {
    return;
  }
  let entries = readStoredSessionDraftEntries();
  for (const [sessionId, draft] of pendingDraftSaves) {
    entries = upsertStoredSessionDraft(entries, sessionId, draft);
  }
  for (const [sessionId, meta] of pendingDraftMetas) {
    entries = upsertStoredSessionDraftMeta(entries, sessionId, meta);
  }
  pendingDraftSaves.clear();
  pendingDraftMetas.clear();
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

/**
 * Debounced rich-field save: the workbench reports the active session's
 * per-turn model selection and reference chips; the draft text written by
 * `scheduleSessionDraftSave` is preserved. Images/files never arrive here —
 * reference attachments are text metadata only by type.
 */
export function scheduleSessionDraftMetaSave(sessionId: string, meta: StoredSessionDraftMeta) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return;
  }
  pendingDraftMetas.set(normalizedSessionId, sanitizeStoredDraftMeta(meta));
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
  pendingDraftMetas.delete(normalizedSessionId);
  writeStoredSessionDraftEntries(
    removeSessionDraftEntry(readStoredSessionDraftEntries(), normalizedSessionId),
  );
}

/** Startup hydration for the workbench in-memory draft map (text only). */
export function readStoredSessionDrafts(): Record<string, string> {
  const drafts: Record<string, string> = {};
  for (const entry of readStoredSessionDraftEntries()) {
    if (entry.draft) {
      drafts[entry.sessionId] = entry.draft;
    }
  }
  return drafts;
}

/** Startup hydration for text + rich fields in one storage read. */
export function readStoredSessionDraftState(): StoredSessionDraftState {
  const state: StoredSessionDraftState = {
    drafts: {},
    turnModelSelections: {},
    referenceAttachments: {},
  };
  for (const entry of readStoredSessionDraftEntries()) {
    if (entry.draft) {
      state.drafts[entry.sessionId] = entry.draft;
    }
    if (entry.turnModelSelection !== undefined) {
      state.turnModelSelections[entry.sessionId] = entry.turnModelSelection;
    }
    if (entry.referenceAttachments?.length) {
      state.referenceAttachments[entry.sessionId] = entry.referenceAttachments;
    }
  }
  return state;
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
  pendingDraftMetas.clear();
}
