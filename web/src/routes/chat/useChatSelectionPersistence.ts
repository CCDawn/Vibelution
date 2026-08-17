import { useEffect, useMemo, useState } from "react";

import type { SessionSummary } from "../../api/types";
import { isVisibleDirectSession } from "../conversationIndexModel";
import {
  chatSelectionStorageKey,
  normalizeChatSelection,
  readStoredChatSelection,
  writeStoredChatSelection,
  type ChatSelectionProjection,
  type ChatSelectionStorage,
  type ChatRouteSelection,
} from "./chatSelectionProjection";

/**
 * The desktop workbench is a single-operator project. Keep this namespace
 * stable across restarts so the last-viewed session survives a reload without
 * coupling the projection to a transient in-memory route instance. Browser
 * storage is still origin-scoped; cross-origin sync belongs to the server
 * preference lane.
 */
export const CHAT_SELECTION_STORAGE_KEY = chatSelectionStorageKey("vibelution", "operator");

type DirectSelectionAvailability = {
  agentIds: Set<string>;
  sessionsById: Map<string, string>;
  firstAgentId?: string;
  firstSessionId?: string;
};

type UseChatSelectionPersistenceOptions = {
  /** Committed Chat route selection (single authority). */
  selection: ChatRouteSelection;
  /** Backend last-viewed session (bare bootstrap hint only). */
  serverSessionId: string | null | undefined;
  activeSessionAgentId: string;
  selectedAgentId: string;
  sessions: SessionSummary[] | undefined;
};

type UseChatSelectionPersistenceResult = {
  /** Stored last-viewed preference (read once; never a navigation input). */
  storedSelection: Partial<ChatSelectionProjection> | null;
  /** Bare-route bootstrap candidate, valid only after the session directory is authoritative. */
  bareRouteBootstrapTarget: ChatRouteSelection | null;
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
 * last-viewed pointer can restore. Running recency on the server must not win.
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
  const availability = availabilityFromSessions(sessions);
  const agentId = cleanAgentForSession(requestedSessionId, stored?.agentId, availability);
  return normalizeChatSelection({ sessionId: requestedSessionId, agentId });
}

function cleanAgentForSession(
  sessionId: string,
  candidateAgentId: string | null | undefined,
  availability: DirectSelectionAvailability,
): string {
  const canonicalAgentId = availability.sessionsById.get(sessionId) ?? "";
  const candidate = String(candidateAgentId || "").trim();
  if (canonicalAgentId) {
    return canonicalAgentId;
  }
  return availability.agentIds.has(candidate) ? candidate : "";
}

/**
 * Bare `/chat` bootstrap priority (one-shot, only after the session directory
 * is authoritative):
 *
 * 1. valid localStorage last-viewed session
 * 2. valid backend last-viewed session
 * 3. first visible direct session
 * 4. no candidate — keep the bare route and show the empty surface
 */
export function resolveBareRouteBootstrapTarget(options: {
  stored: Partial<ChatSelectionProjection> | null | undefined;
  serverSessionId: string | null | undefined;
  sessions: SessionSummary[] | undefined;
}): ChatRouteSelection | null {
  const sessions = options.sessions;
  if (!sessions) {
    return null;
  }
  const visibility = availabilityFromSessions(sessions);
  const storedTarget = resolveStoredDirectChatSelection(options.stored ?? null, sessions);
  if (storedTarget?.sessionId) {
    return { kind: "session", sessionId: storedTarget.sessionId };
  }
  const serverSessionId = String(options.serverSessionId || "").trim();
  if (serverSessionId && visibility.sessionsById.has(serverSessionId)) {
    return { kind: "session", sessionId: serverSessionId };
  }
  const firstSessionId = String(visibility.firstSessionId || "").trim();
  if (firstSessionId) {
    return { kind: "session", sessionId: firstSessionId };
  }
  return null;
}

/**
 * localStorage is a last-viewed preference only:
 *
 * - bare route: provide the bootstrap candidate (explicit routes always skip it);
 * - committed session route: passively write the preference back;
 * - room / project bus / invalid routes: no read that can drive navigation.
 */
export function useChatSelectionPersistence({
  selection,
  serverSessionId,
  activeSessionAgentId,
  selectedAgentId,
  sessions,
}: UseChatSelectionPersistenceOptions): UseChatSelectionPersistenceResult {
  const [storedSelection] = useState<Partial<ChatSelectionProjection> | null>(() =>
    readStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY),
  );

  const bareRouteBootstrapTarget = useMemo(() => {
    if (selection.kind !== "bare") {
      return null;
    }
    return resolveBareRouteBootstrapTarget({
      stored: storedSelection,
      serverSessionId,
      sessions,
    });
  }, [selection.kind, serverSessionId, sessions, storedSelection]);

  // Passively persist the committed direct session (never reads back into navigation).
  const committedSessionId = selection.kind === "session" ? selection.sessionId : "";
  useEffect(() => {
    if (!committedSessionId) {
      return;
    }
    const knownSession = sessions?.some(
      (session) => String(session.id || "").trim() === committedSessionId && isVisibleDirectSession(session),
    );
    if (sessions && !knownSession) {
      return;
    }
    writeStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY, normalizeChatSelection({
      agentId: activeSessionAgentId || selectedAgentId,
      sessionId: committedSessionId,
    }));
  }, [activeSessionAgentId, committedSessionId, selectedAgentId, sessions]);

  return {
    storedSelection,
    bareRouteBootstrapTarget,
  };
}
