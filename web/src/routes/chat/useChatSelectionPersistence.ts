import { useEffect, useRef } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { SessionSummary } from "../../api/types";
import { isVisibleDirectSession } from "../conversationIndexModel";
import {
  chatSelectionStorageKey,
  normalizeChatSelection,
  readStoredChatSelection,
  resolveChatSelection,
  writeStoredChatSelection,
  type ChatSelectionProjection,
  type ChatSelectionStorage,
} from "./chatSelectionProjection";

/**
 * The desktop workbench is a single-operator project. Keep this namespace
 * stable across restarts so a tab switch survives a reload without coupling
 * the projection to a transient in-memory route instance. Browser storage is
 * still origin-scoped; cross-origin sync belongs to the server preference lane.
 */
export const CHAT_SELECTION_STORAGE_KEY = chatSelectionStorageKey("vibelution", "operator");

type DirectSelectionAvailability = {
  agentIds: Set<string>;
  sessionsById: Map<string, string>;
  firstAgentId?: string;
  firstSessionId?: string;
};

type UseChatSelectionPersistenceOptions = {
  requestedSessionId: string;
  requestedRoomId: string;
  activeSessionId?: string | null;
  activeSessionAgentId: string;
  selectedAgentId: string;
  sessions: SessionSummary[] | undefined;
  setActiveSession: (sessionId: string) => void;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  reselectDirectSession?: (sessionId: string) => void;
};

function availabilityFromSessions(sessions: SessionSummary[]): DirectSelectionAvailability {
  const sessionsById = new Map<string, string>();
  const agentIds = new Set<string>();
  const visibleSessions = sessions.filter(isVisibleDirectSession);
  for (const session of visibleSessions) {
    const sessionId = String(session.id || "").trim();
    const agentId = String(session.agentId || "").trim();
    if (!sessionId) {
      continue;
    }
    sessionsById.set(sessionId, agentId);
    if (agentId) {
      agentIds.add(agentId);
    }
  }
  return {
    agentIds,
    sessionsById,
    firstAgentId: visibleSessions.find((session) => String(session.agentId || "").trim())?.agentId,
    firstSessionId: visibleSessions[0]?.id,
  };
}

function chatSelectionStorage(): Storage | undefined {
  if (typeof window === "undefined") {
    return undefined;
  }
  try {
    return window.localStorage;
  } catch {
    return undefined;
  }
}

/**
 * Server `active_conversation_id` must not paint before a still-valid local
 * viewing pointer can restore. Running recency on the server must not win.
 */
export function storedChatSelectionBlocksServerBootstrap(
  sessions: SessionSummary[] | undefined,
  storage?: ChatSelectionStorage,
): boolean {
  const storedSessionId = String(
    readStoredChatSelection(storage ?? chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY)?.sessionId || "",
  ).trim();
  if (!storedSessionId) {
    return false;
  }
  if (!sessions) {
    return true;
  }
  return sessions.some(
    (session) => String(session.id || "").trim() === storedSessionId && isVisibleDirectSession(session),
  );
}

export function resolveStoredDirectChatSelection(
  stored: Partial<ChatSelectionProjection> | null,
  sessions: SessionSummary[],
): ChatSelectionProjection | null {
  const requestedSessionId = String(stored?.sessionId || "").trim();
  if (
    !requestedSessionId
    || !sessions.some(
      (session) => String(session.id || "").trim() === requestedSessionId && isVisibleDirectSession(session),
    )
  ) {
    return null;
  }
  const resolved = resolveChatSelection({
    local: stored,
    availability: availabilityFromSessions(sessions),
  });
  return resolved.source === "local" && resolved.selection.sessionId === requestedSessionId
    ? normalizeChatSelection(resolved.selection)
    : null;
}

/**
 * Restores the last valid direct Agent/session only when the canonical session
 * index is available. Explicit URL targets always win and no stale local id is
 * ever sent to the session selection endpoint.
 */
export function useChatSelectionPersistence({
  requestedSessionId,
  requestedRoomId,
  activeSessionId,
  activeSessionAgentId,
  selectedAgentId,
  sessions,
  setActiveSession,
  setSelectedAgentId,
  reselectDirectSession,
}: UseChatSelectionPersistenceOptions): void {
  const storedSelectionRef = useRef<Partial<ChatSelectionProjection> | null | undefined>(undefined);
  const restoreSettledRef = useRef(false);
  const skipPersistOnceRef = useRef(false);

  useEffect(() => {
    if (storedSelectionRef.current !== undefined) {
      return;
    }
    storedSelectionRef.current = readStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY);
  }, []);

  useEffect(() => {
    if (restoreSettledRef.current) {
      return;
    }
    if (requestedSessionId || requestedRoomId) {
      restoreSettledRef.current = true;
      return;
    }
    if (!sessions) {
      return;
    }

    const storedSelection = resolveStoredDirectChatSelection(storedSelectionRef.current ?? null, sessions);
    restoreSettledRef.current = true;
    if (!storedSelection?.sessionId) {
      return;
    }
    setSelectedAgentId(storedSelection.agentId || "");
    if (storedSelection.sessionId !== String(activeSessionId || "").trim()) {
      skipPersistOnceRef.current = true;
      setActiveSession(storedSelection.sessionId);
      reselectDirectSession?.(storedSelection.sessionId);
    }
  }, [
    activeSessionId,
    requestedRoomId,
    requestedSessionId,
    sessions,
    reselectDirectSession,
    setActiveSession,
    setSelectedAgentId,
  ]);

  useEffect(() => {
    if (!restoreSettledRef.current) {
      return;
    }
    if (skipPersistOnceRef.current) {
      skipPersistOnceRef.current = false;
      return;
    }
    const sessionId = String(activeSessionId || "").trim();
    if (!sessionId) {
      return;
    }
    const knownSession = sessions?.some(
      (session) => String(session.id || "").trim() === sessionId && isVisibleDirectSession(session),
    );
    if (sessions && !knownSession) {
      return;
    }
    writeStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY, normalizeChatSelection({
      agentId: activeSessionAgentId || selectedAgentId,
      sessionId,
    }));
  }, [activeSessionAgentId, activeSessionId, selectedAgentId, sessions]);
}
