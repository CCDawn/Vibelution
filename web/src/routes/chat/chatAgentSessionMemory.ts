/**
 * Per-Agent last-viewed session. Running recency must not decide which
 * session opens when the operator clicks an Agent in the directory.
 */

import { isSessionDeleteTombstoned } from "../sessionDeleteTombstone";

export const CHAT_AGENT_LAST_SESSION_STORAGE_KEY = "vibelution.chat-agent-last-session.v1:vibelution:operator";

export type ChatAgentLastSessionMap = Record<string, string>;

type ChatAgentSessionStorage = Pick<Storage, "getItem" | "setItem">;

function cleanId(value: string | null | undefined) {
  return String(value ?? "").trim();
}

export function normalizeAgentLastSessionMap(
  value: unknown,
): ChatAgentLastSessionMap {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const next: ChatAgentLastSessionMap = {};
  for (const [agentId, sessionId] of Object.entries(value as Record<string, unknown>)) {
    const normalizedAgentId = cleanId(agentId);
    const normalizedSessionId = cleanId(typeof sessionId === "string" ? sessionId : "");
    if (normalizedAgentId && normalizedSessionId) {
      next[normalizedAgentId] = normalizedSessionId;
    }
  }
  return next;
}

export function readAgentLastSessionMap(
  storage: ChatAgentSessionStorage | undefined,
  key = CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
): ChatAgentLastSessionMap {
  if (!storage) {
    return {};
  }
  try {
    const raw = storage.getItem(key);
    if (!raw) {
      return {};
    }
    return normalizeAgentLastSessionMap(JSON.parse(raw) as unknown);
  } catch {
    return {};
  }
}

function writeAgentLastSessionMap(
  storage: ChatAgentSessionStorage | undefined,
  key: string,
  map: ChatAgentLastSessionMap,
): void {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(key, JSON.stringify(map));
  } catch {
    // Private-mode quota failures must not block the in-memory selection.
  }
}

export function rememberAgentLastSession(
  agentId: string,
  sessionId: string,
  storage: ChatAgentSessionStorage | undefined,
  key = CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
): ChatAgentLastSessionMap {
  const normalizedAgentId = cleanId(agentId);
  const normalizedSessionId = cleanId(sessionId);
  const current = readAgentLastSessionMap(storage, key);
  if (!normalizedAgentId || !normalizedSessionId) {
    return current;
  }
  if (current[normalizedAgentId] === normalizedSessionId) {
    return current;
  }
  const next = { ...current, [normalizedAgentId]: normalizedSessionId };
  writeAgentLastSessionMap(storage, key, next);
  return next;
}

/**
 * Drop one Agent's last-viewed pointer (its session no longer exists).
 */
export function forgetAgentLastSession(
  agentId: string,
  storage: ChatAgentSessionStorage | undefined,
  key = CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
): ChatAgentLastSessionMap {
  const normalizedAgentId = cleanId(agentId);
  const current = readAgentLastSessionMap(storage, key);
  if (!normalizedAgentId || !Object.prototype.hasOwnProperty.call(current, normalizedAgentId)) {
    return current;
  }
  const next = { ...current };
  delete next[normalizedAgentId];
  writeAgentLastSessionMap(storage, key, next);
  return next;
}

/**
 * Drop every last-viewed pointer that references a session, for any Agent.
 * Used when a 404 proves the session is gone regardless of which Agent owned it.
 */
export function forgetAgentLastSessionBySessionId(
  sessionId: string,
  storage: ChatAgentSessionStorage | undefined,
  key = CHAT_AGENT_LAST_SESSION_STORAGE_KEY,
): ChatAgentLastSessionMap {
  const normalizedSessionId = cleanId(sessionId);
  const current = readAgentLastSessionMap(storage, key);
  if (!normalizedSessionId) {
    return current;
  }
  const next: ChatAgentLastSessionMap = {};
  let changed = false;
  for (const [agentId, lastSessionId] of Object.entries(current)) {
    if (lastSessionId === normalizedSessionId) {
      changed = true;
      continue;
    }
    next[agentId] = lastSessionId;
  }
  if (!changed) {
    return current;
  }
  writeAgentLastSessionMap(storage, key, next);
  return next;
}

export function lastSessionForAgent(
  agentId: string,
  map: ChatAgentLastSessionMap | null | undefined,
): string {
  return cleanId(map?.[cleanId(agentId)]);
}

export function resolveAgentOpenSessionId(options: {
  lastSessionId?: string | null;
  knownSessionIds?: ReadonlySet<string> | readonly string[];
  latestSessionId?: string | null;
  directSessionId?: string | null;
}): string {
  const lastSessionId = cleanId(options.lastSessionId);
  if (lastSessionId && !isSessionDeleteTombstoned(lastSessionId)) {
    // Trust last-viewed even when the Agent query has not loaded that row yet
    // (child sessions, pagination). Tombstoned ids are skipped so the directory
    // never reopens a session the operator just deleted; other stale ids still
    // settle on the unavailable surface at select instead of silently swapping.
    return lastSessionId;
  }
  const known = options.knownSessionIds instanceof Set
    ? options.knownSessionIds
    : new Set(
      [...(options.knownSessionIds ?? [])]
        .map((sessionId) => cleanId(sessionId))
        .filter(Boolean),
    );
  const candidates = [
    options.latestSessionId,
    options.directSessionId,
  ].map((sessionId) => cleanId(sessionId)).filter(Boolean);
  for (const sessionId of candidates) {
    if (isSessionDeleteTombstoned(sessionId)) {
      continue;
    }
    if (known.size === 0 || known.has(sessionId)) {
      return sessionId;
    }
  }
  return "";
}

export function chatAgentSessionStorage(): Storage | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}
