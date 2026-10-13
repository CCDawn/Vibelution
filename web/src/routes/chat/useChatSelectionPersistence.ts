import { useEffect, useMemo, useRef } from "react";
import { useLocation } from "react-router-dom";

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
  /** Current local fallback preference; explicit route selection never reads it. */
  storedSelection: Partial<ChatSelectionProjection> | null;
  /** Bare-route bootstrap candidate, valid only after the session directory is authoritative. */
  bareRouteBootstrapTarget: ChatRouteSelection | null;
};

function availabilityFromSessions(sessions: SessionSummary[]): DirectSelectionAvailability {
  const sessionsById = new Map<string, string>();
  const agentIds = new Set<string>();
  const visibleSessions = sessions.filter((session) => isVisibleDirectSession(session));
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

/** Safely read the operator's current Chat preference outside the hook. */
export function readCurrentChatSelectionPreference(): Partial<ChatSelectionProjection> | null {
  return readStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY);
}

function currentRouteMatchesChatSession(
  location: { pathname: string; search: string },
  sessionId: string,
): boolean {
  if (!["/chat", "/finance"].includes(location.pathname.replace(/\/+$/, "") || "/")) {
    return false;
  }
  return String(new URLSearchParams(location.search).get("session") || "").trim() === sessionId;
}

/**
 * Server `active_conversation_id` must not paint before a still-valid local
 * session or Agent preference can restore. Running recency on the server must not win.
 */
export function storedChatSelectionBlocksServerBootstrap(
  sessions: SessionSummary[] | undefined,
  storage?: ChatSelectionStorage,
): boolean {
  const stored = readStoredChatSelection(storage ?? chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY);
  if (!String(stored?.sessionId || "").trim() && !String(stored?.agentId || "").trim()) {
    return false;
  }
  if (!sessions) {
    return true;
  }
  if (resolveStoredDirectChatSelection(stored, sessions)) {
    return true;
  }
  return resolveStoredAgentDirectChatSelection(stored, sessions) !== null;
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

function resolveStoredAgentDirectChatSelection(
  stored: Partial<ChatSelectionProjection> | null | undefined,
  sessions: SessionSummary[],
): ChatSelectionProjection | null {
  const agentId = String(stored?.agentId || "").trim();
  if (!agentId) {
    return null;
  }
  const session = sessions.find((candidate) =>
    isVisibleDirectSession(candidate)
    && String(candidate.agentId || "").trim() === agentId,
  );
  const sessionId = String(session?.id || "").trim();
  return sessionId ? normalizeChatSelection({ agentId, sessionId }) : null;
}

/**
 * Bare `/chat` bootstrap priority (one-shot, only after the session directory
 * is authoritative):
 *
 * 1. valid localStorage last-viewed session
 * 2. first visible session for the locally stored Agent
 * 3. valid backend last-viewed session
 * 4. first visible direct session
 * 5. no candidate — keep the bare route and show the empty surface
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
  const storedAgentTarget = resolveStoredAgentDirectChatSelection(options.stored, sessions);
  if (storedAgentTarget?.sessionId) {
    return { kind: "session", sessionId: storedAgentTarget.sessionId };
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
 * - committed session route: passively write the preference back only when
 *   the current Chat/Finance URL selects that same session;
 * - room / project bus / invalid routes: no read that can drive navigation.
 */
export function useChatSelectionPersistence({
  selection,
  serverSessionId,
  activeSessionAgentId,
  selectedAgentId,
  sessions,
}: UseChatSelectionPersistenceOptions): UseChatSelectionPersistenceResult {
  const routeLocation = useLocation();
  // Re-read when entering a bare route. A kept-alive Chat instance may have
  // mounted before another route updated the shared operator preference.
  const storedSelection = useMemo(
    () => readCurrentChatSelectionPreference(),
    [routeLocation.key, routeLocation.pathname, routeLocation.search, selection.kind],
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
  const lastPersistedRouteRef = useRef("");
  useEffect(() => {
    if (!committedSessionId) {
      lastPersistedRouteRef.current = "";
      return;
    }
    const routeIdentity = `${routeLocation.pathname}${routeLocation.search}#${routeLocation.key}`;
    if (!currentRouteMatchesChatSession(routeLocation, committedSessionId)) {
      lastPersistedRouteRef.current = "";
      return;
    }
    if (lastPersistedRouteRef.current === routeIdentity) {
      return;
    }
    const knownSession = sessions?.find(
      (session) => String(session.id || "").trim() === committedSessionId && isVisibleDirectSession(session),
    );
    if (!knownSession) {
      return;
    }
    const canonicalAgentId = String(knownSession.agentId || "").trim()
      || String(activeSessionAgentId || "").trim()
      || String(selectedAgentId || "").trim();
    if (!canonicalAgentId) {
      return;
    }
    lastPersistedRouteRef.current = routeIdentity;
    writeStoredChatSelection(chatSelectionStorage(), CHAT_SELECTION_STORAGE_KEY, normalizeChatSelection({
      agentId: canonicalAgentId,
      sessionId: committedSessionId,
    }));
  }, [activeSessionAgentId, committedSessionId, routeLocation.key, routeLocation.pathname, routeLocation.search, selectedAgentId, sessions]);

  return {
    storedSelection,
    bareRouteBootstrapTarget,
  };
}
