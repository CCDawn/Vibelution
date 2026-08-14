export type ChatSelectionSurface = "agent" | "session" | "room";

export type ChatSelectionProjection = {
  agentId: string | null;
  sessionId: string | null;
  roomId: string | null;
  tabId: string | null;
};

/**
 * Route-only active selection (single authority).
 *
 * The committed React Router URL is the only source of the current Chat
 * surface. `session` / `room` / `project_bus` are mutually exclusive route
 * targets; `bare` is the uncapped `/chat` entry; `invalid` is an explicit URL
 * that cannot be interpreted and must render an unavailable surface instead of
 * silently selecting another session.
 */
export type ChatRouteSelection =
  | { kind: "session"; sessionId: string }
  | { kind: "room"; roomId: string }
  | { kind: "project_bus" }
  | { kind: "bare" }
  | { kind: "invalid"; reason: string };

/** Explicit Project Agent Bus route target (not a local sentinel). */
export const PROJECT_AGENT_BUS_ROOM_ID = "__project_agent_bus__";

export function parseChatRouteSelection(search: string): ChatRouteSelection {
  const params = new URLSearchParams(search);
  const sessionId = cleanId(params.get("session"));
  const roomId = cleanId(params.get("room"));
  if (sessionId && roomId) {
    return { kind: "invalid", reason: "conflicting_session_and_room" };
  }
  if (roomId === PROJECT_AGENT_BUS_ROOM_ID) {
    return { kind: "project_bus" };
  }
  if (roomId) {
    return { kind: "room", roomId };
  }
  if (sessionId) {
    return { kind: "session", sessionId };
  }
  return { kind: "bare" };
}

/**
 * Serialize a chat route target while preserving unrelated query params
 * (focusTask / focusTurn / returnTo / returnLabel / filter …). Only the
 * session/room selection keys are owned by the Chat route domain.
 */
export function serializeChatRouteSelection(search: string, selection: ChatRouteSelection): string {
  const params = new URLSearchParams(search);
  params.delete("session");
  params.delete("room");
  if (selection.kind === "session") {
    params.set("session", selection.sessionId);
  } else if (selection.kind === "room") {
    params.set("room", selection.roomId);
  } else if (selection.kind === "project_bus") {
    params.set("room", PROJECT_AGENT_BUS_ROOM_ID);
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

/** Comparable route identity for compare-and-swap transitions. */
export function chatRouteSelectionKey(selection: ChatRouteSelection): string {
  switch (selection.kind) {
    case "session":
      return `session:${selection.sessionId}`;
    case "room":
      return `room:${selection.roomId}`;
    case "project_bus":
      return "room:__project_agent_bus__";
    case "bare":
      return "bare";
    case "invalid":
      return `invalid:${selection.reason}`;
  }
}

export function chatRouteSelectionsEqual(
  current: ChatRouteSelection,
  expected: ChatRouteSelection,
): boolean {
  if (current.kind !== expected.kind) {
    return false;
  }
  switch (current.kind) {
    case "session":
      return expected.kind === "session" && current.sessionId === expected.sessionId;
    case "room":
      return expected.kind === "room" && current.roomId === expected.roomId;
    default:
      return true;
  }
}

export function activeSessionIdFromRouteSelection(selection: ChatRouteSelection): string {
  return selection.kind === "session" ? selection.sessionId : "";
}

export function activeGroupRoomIdFromRouteSelection(selection: ChatRouteSelection): string {
  if (selection.kind === "project_bus") {
    return PROJECT_AGENT_BUS_ROOM_ID;
  }
  return selection.kind === "room" ? selection.roomId : "";
}

export type ChatSelectionAvailability = {
  agentIds?: ReadonlySet<string>;
  sessionsById?: ReadonlyMap<string, string>;
  firstAgentId?: string | null;
  firstSessionId?: string | null;
};

export type ChatSelectionSource = "url" | "local" | "server" | "default";

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
