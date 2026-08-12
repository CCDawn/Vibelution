import { type QueryClient } from "@tanstack/react-query";
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";
import type { NavigateFunction } from "react-router-dom";

import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, ConversationSummary, SessionSummary } from "../../api/types";
import { useChatWorkbenchStore } from "../../store/chatWorkbenchStore";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import { isVisibleDirectSession } from "../conversationIndexModel";
import { removeDeletedSessionFromConversations } from "./chatSessionDetailHelpers";
import { resolveArchivedSessionRouteTransition } from "./chatSessionRouteSync";

type UseChatArchivedAgentRetirementOptions = {
  activeSessionId: string | null | undefined;
  requestedSessionId: string | null | undefined;
  pathname: string;
  search: string;
  navigate: NavigateFunction;
  queryClient: QueryClient;
  clearSessionTransientUiState: (sessionId: string) => void;
  forgetSessionDetailPaint: (sessionId: string) => void;
  removeSessionWorkspace: (sessionId: string, nextActiveSessionId?: string | null) => void;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setActiveSession: (sessionId: string) => void;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  latestDirectSessionSelectionRef: MutableRefObject<string>;
  latestDirectSessionSelectionAtRef: MutableRefObject<number>;
  directSessionSelectionGenerationRef: MutableRefObject<number>;
  retiredDirectSessionIdsRef: MutableRefObject<ReadonlySet<string>>;
};

type RetireArchivedAgentSessionsOptions = {
  agentId: string;
  archivedSessionIds: readonly string[];
  sessions: readonly SessionSummary[];
  remainingAgents: readonly AgentInstance[];
};

/**
 * Removes an archived Agent's sessions from the normal Chat selection surface.
 * This is deliberately Chat-only: the retained archive remains available in
 * Agent Management, while Chat must not keep a sealed session selected.
 */
export function useChatArchivedAgentRetirement({
  activeSessionId,
  requestedSessionId,
  pathname,
  search,
  navigate,
  queryClient,
  clearSessionTransientUiState,
  forgetSessionDetailPaint,
  removeSessionWorkspace,
  setSelectedAgentId,
  setActiveSession,
  setSessionComposerErrors,
  latestDirectSessionSelectionRef,
  latestDirectSessionSelectionAtRef,
  directSessionSelectionGenerationRef,
  retiredDirectSessionIdsRef,
}: UseChatArchivedAgentRetirementOptions) {
  return useCallback((options: RetireArchivedAgentSessionsOptions) => {
    const archivedSessionIds = [...new Set(
      options.archivedSessionIds.map((sessionId) => String(sessionId || "").trim()).filter(Boolean),
    )];
    const archivedSessionIdSet = new Set(archivedSessionIds);
    const remainingAgentIds = new Set(options.remainingAgents.map((agent) => agent.agentId));
    const currentActiveSessionId = String(
      useChatWorkbenchStore.getState().activeSessionId || activeSessionId || "",
    ).trim();
    const currentActiveSession = options.sessions.find((session) => session.id === currentActiveSessionId);
    const fallbackSession = (
      currentActiveSession
      && remainingAgentIds.has(String(currentActiveSession.agentId || "").trim())
      && isVisibleDirectSession(currentActiveSession)
    )
      ? currentActiveSession
      : options.sessions.find(
        (session) => (
          !archivedSessionIdSet.has(session.id)
          && remainingAgentIds.has(String(session.agentId || "").trim())
          && isVisibleDirectSession(session)
        ),
      );
    const fallbackAgentId = String(
      fallbackSession?.agentId
      || options.remainingAgents.find((agent) => String(agent.status || "").trim() !== "archived")?.agentId
      || "",
    ).trim();
    const archiveRouteTransition = resolveArchivedSessionRouteTransition({
      archivedSessionIds,
      activeSessionId: currentActiveSessionId,
      requestedSessionId,
      fallbackSessionId: fallbackSession?.id,
    });
    const latestIntentArchived = archivedSessionIdSet.has(latestDirectSessionSelectionRef.current);
    if (archiveRouteTransition.shouldRetireSelection || latestIntentArchived) {
      const retiredSessionIds = new Set(retiredDirectSessionIdsRef.current);
      archivedSessionIds.forEach((sessionId) => retiredSessionIds.add(sessionId));
      while (retiredSessionIds.size > 64) {
        const oldestSessionId = retiredSessionIds.values().next().value;
        if (!oldestSessionId) {
          break;
        }
        retiredSessionIds.delete(oldestSessionId);
      }
      retiredDirectSessionIdsRef.current = retiredSessionIds;
      directSessionSelectionGenerationRef.current += 1;
      latestDirectSessionSelectionRef.current = fallbackSession?.id || "";
      latestDirectSessionSelectionAtRef.current = Date.now();
    }

    updateSessionSummaryCaches(queryClient, (sessions) =>
      sessions?.filter((session) => !archivedSessionIdSet.has(session.id)),
    );
    queryClient.setQueryData<ConversationSummary[]>(queryKeys.conversations(), (conversations) =>
      archivedSessionIds.reduce(
        (current, sessionId) => removeDeletedSessionFromConversations(current, sessionId),
        conversations,
      ),
    );
    archivedSessionIds.forEach((sessionId) => {
      clearSessionTransientUiState(sessionId);
      forgetSessionDetailPaint(sessionId);
      removeSessionWorkspace(sessionId, fallbackSession?.id || null);
    });
    setSelectedAgentId((current) => current === options.agentId ? fallbackAgentId : current);
    if (archiveRouteTransition.nextActiveSessionId !== currentActiveSessionId) {
      setActiveSession(archiveRouteTransition.nextActiveSessionId);
    }
    if (archiveRouteTransition.nextRequestedSessionId !== requestedSessionId) {
      const nextSearchParams = new URLSearchParams(search);
      if (archiveRouteTransition.nextRequestedSessionId) {
        nextSearchParams.set("session", archiveRouteTransition.nextRequestedSessionId);
      } else {
        nextSearchParams.delete("session");
      }
      const nextSearch = nextSearchParams.toString();
      navigate(`${pathname}${nextSearch ? `?${nextSearch}` : ""}`, { replace: true });
    }
    setSessionComposerErrors((current) => {
      const next: Record<string, string> = { ...current, __sessions__: "" };
      archivedSessionIds.forEach((sessionId) => delete next[sessionId]);
      return next;
    });
  }, [
    activeSessionId,
    clearSessionTransientUiState,
    directSessionSelectionGenerationRef,
    forgetSessionDetailPaint,
    latestDirectSessionSelectionAtRef,
    latestDirectSessionSelectionRef,
    navigate,
    pathname,
    queryClient,
    removeSessionWorkspace,
    requestedSessionId,
    retiredDirectSessionIdsRef,
    search,
    setActiveSession,
    setSelectedAgentId,
    setSessionComposerErrors,
  ]);
}
