/**
 * Per-Agent last-viewed session. Running recency must not decide which
 * session opens when the operator clicks an Agent in the directory.
 */

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
  if (!storage) {
    return next;
  }
  try {
    storage.setItem(key, JSON.stringify(next));
  } catch {
    // Private-mode quota failures must not block the in-memory selection.
  }
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
  if (lastSessionId) {
    // Trust last-viewed even when the Agent query has not loaded that row yet
    // (child sessions, pagination). A deleted id fails at select, not here.
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
