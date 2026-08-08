export type ChatSelectionSurface = "agent" | "session" | "room";

export type ChatSelectionProjection = {
  agentId: string | null;
  sessionId: string | null;
  roomId: string | null;
  tabId: string | null;
};

export type ChatSelectionSource = "url" | "local" | "server" | "default";

export type ChatSelectionAvailability = {
  agentIds?: ReadonlySet<string>;
  sessionsById?: ReadonlyMap<string, string>;
  firstAgentId?: string | null;
  firstSessionId?: string | null;
};

export type ChatSelectionStorage = Pick<Storage, "getItem" | "setItem">;

export const CHAT_SELECTION_STORAGE_VERSION = 1;
export const EMPTY_CHAT_SELECTION: ChatSelectionProjection = {
  agentId: null,
  sessionId: null,
  roomId: null,
  tabId: null,
};

function cleanId(value: string | null | undefined) {
  const normalized = String(value ?? "").trim();
  return normalized || null;
}

export function normalizeChatSelection(
  value: Partial<ChatSelectionProjection> | null | undefined,
): ChatSelectionProjection {
  const roomId = cleanId(value?.roomId);
  const sessionId = roomId ? null : cleanId(value?.sessionId);
  const agentId = cleanId(value?.agentId);
  return {
    agentId,
    sessionId,
    roomId,
    tabId: cleanId(value?.tabId),
  };
}

export function selectionSurface(selection: ChatSelectionProjection): ChatSelectionSurface | null {
  if (selection.roomId) {
    return "room";
  }
  if (selection.sessionId) {
    return "session";
  }
  if (selection.agentId) {
    return "agent";
  }
  return null;
}

export function parseChatSelectionSearch(search: string): Partial<ChatSelectionProjection> {
  const params = new URLSearchParams(search);
  return {
    agentId: cleanId(params.get("agent")),
    sessionId: cleanId(params.get("session")),
    roomId: cleanId(params.get("room")),
    tabId: cleanId(params.get("tab")),
  };
}

export function serializeChatSelectionSearch(
  search: string,
  selection: Partial<ChatSelectionProjection>,
) {
  const params = new URLSearchParams(search);
  const normalized = normalizeChatSelection(selection);
  const values: Record<string, string | null> = {
    agent: normalized.agentId,
    session: normalized.sessionId,
    room: normalized.roomId,
    tab: normalized.tabId,
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) {
      params.set(key, value);
    } else {
      params.delete(key);
    }
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

export function chatSelectionStorageKey(projectId: string, userId: string) {
  const project = encodeURIComponent(String(projectId || "default").trim() || "default");
  const user = encodeURIComponent(String(userId || "anonymous").trim() || "anonymous");
  return `vibelution.chat-selection.v${CHAT_SELECTION_STORAGE_VERSION}:${project}:${user}`;
}

export function readStoredChatSelection(
  storage: ChatSelectionStorage | undefined,
  key: string,
): Partial<ChatSelectionProjection> | null {
  if (!storage) {
    return null;
  }
  try {
    const raw = storage.getItem(key);
    if (!raw) {
      return null;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return normalizeChatSelection(parsed as Partial<ChatSelectionProjection>);
  } catch {
    return null;
  }
}

export function writeStoredChatSelection(
  storage: ChatSelectionStorage | undefined,
  key: string,
  selection: Partial<ChatSelectionProjection>,
) {
  if (!storage) {
    return;
  }
  try {
    storage.setItem(key, JSON.stringify(normalizeChatSelection(selection)));
  } catch {
    // Persistence is a fallback. A blocked/private storage implementation must
    // never prevent the in-memory selection from changing.
  }
}

export function resolveChatSelection({
  url,
  local,
  server,
  availability,
}: {
  url?: Partial<ChatSelectionProjection> | null;
  local?: Partial<ChatSelectionProjection> | null;
  server?: Partial<ChatSelectionProjection> | null;
  availability?: ChatSelectionAvailability;
}): { selection: ChatSelectionProjection; source: ChatSelectionSource } {
  const sources: Array<[ChatSelectionSource, Partial<ChatSelectionProjection> | null | undefined]> = [
    ["url", url],
    ["local", local],
    ["server", server],
  ];
  for (const [source, candidate] of sources) {
    const normalized = normalizeChatSelection(candidate);
    if (!selectionSurface(normalized)) {
      continue;
    }
    return {
      selection: reconcileChatSelection(normalized, availability),
      source,
    };
  }
  const fallback = normalizeChatSelection({
    agentId: availability?.firstAgentId,
    sessionId: availability?.firstSessionId,
  });
  return { selection: reconcileChatSelection(fallback, availability), source: "default" };
}

export function reconcileChatSelection(
  selection: Partial<ChatSelectionProjection>,
  availability?: ChatSelectionAvailability,
): ChatSelectionProjection {
  const normalized = normalizeChatSelection(selection);
  if (!availability) {
    return normalized;
  }
  const sessionsById = availability.sessionsById;
  let sessionId = normalized.sessionId;
  let agentId = normalized.agentId;
  if (sessionId && sessionsById && !sessionsById.has(sessionId)) {
    sessionId = null;
  }
  if (sessionId && sessionsById) {
    agentId = cleanId(sessionsById.get(sessionId)) || agentId;
  }
  if (agentId && availability.agentIds && !availability.agentIds.has(agentId)) {
    agentId = null;
  }
  if (!agentId && sessionId && sessionsById) {
    agentId = cleanId(sessionsById.get(sessionId));
  }
  if (!agentId && !normalized.roomId) {
    agentId = cleanId(availability.firstAgentId);
  }
  if (!sessionId && !normalized.roomId && availability.firstSessionId && agentId === availability.firstAgentId) {
    sessionId = cleanId(availability.firstSessionId);
  }
  return normalizeChatSelection({ ...normalized, agentId, sessionId });
}

export function selectChatAgent(
  selection: Partial<ChatSelectionProjection>,
  agentId: string,
  preferredSessionId?: string | null,
) {
  return normalizeChatSelection({
    ...selection,
    agentId,
    sessionId: preferredSessionId ?? null,
    roomId: null,
  });
}

export function selectChatSession(
  selection: Partial<ChatSelectionProjection>,
  sessionId: string,
  agentId?: string | null,
) {
  return normalizeChatSelection({
    ...selection,
    sessionId,
    agentId: agentId ?? selection.agentId,
    roomId: null,
  });
}

export function selectChatRoom(
  selection: Partial<ChatSelectionProjection>,
  roomId: string,
) {
  return normalizeChatSelection({ ...selection, roomId, sessionId: null });
}
