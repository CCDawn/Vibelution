import { type QueryClient } from "@tanstack/react-query";
import { useCallback, type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, ConversationSummary, SessionSummary } from "../../api/types";
import { updateSessionSummaryCaches } from "../chatSessionIndexQuery";
import { isVisibleDirectSession } from "../conversationIndexModel";
import { removeDeletedSessionFromConversations } from "./chatSessionDetailHelpers";
import { resolveArchivedSessionRouteTransition } from "./chatSessionRouteSync";
import type { ChatRouteSelection } from "./chatSelectionProjection";

type ChatRouteRetirementActions = {
  replaceIfStillViewing: (expected: ChatRouteSelection, next: ChatRouteSelection) => boolean;
};

type UseChatArchivedAgentRetirementOptions = {
  requestedSessionId: string | null | undefined;
  queryClient: QueryClient;
  clearSessionTransientUiState: (sessionId: string) => void;
  forgetSessionDetailPaint: (sessionId: string) => void;
  removeSessionWorkspace: (sessionId: string) => void;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  chatRoute: ChatRouteRetirementActions;
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
 *
 * The explicit route target may be retired after a user-confirmed archive;
 * the transition is compare-and-swap, so a user who already navigated away
 * keeps their page.
 */
export function useChatArchivedAgentRetirement({
  requestedSessionId,
  queryClient,
  clearSessionTransientUiState,
  forgetSessionDetailPaint,
  removeSessionWorkspace,
  setSelectedAgentId,
  setSessionComposerErrors,
  chatRoute,
  directSessionSelectionGenerationRef,
  retiredDirectSessionIdsRef,
}: UseChatArchivedAgentRetirementOptions) {
  return useCallback((options: RetireArchivedAgentSessionsOptions) => {
    const archivedSessionIds = [...new Set(
      options.archivedSessionIds.map((sessionId) => String(sessionId || "").trim()).filter(Boolean),
    )];
    const archivedSessionIdSet = new Set(archivedSessionIds);
    const remainingAgentIds = new Set(options.remainingAgents.map((agent) => agent.agentId));
    const requestedId = String(requestedSessionId || "").trim();
    const requestedSession = requestedId
      ? options.sessions.find((session) => session.id === requestedId)
      : undefined;
    const fallbackSession = (
      requestedSession
      && !archivedSessionIdSet.has(requestedSession.id)
      && remainingAgentIds.has(String(requestedSession.agentId || "").trim())
      && isVisibleDirectSession(requestedSession)
    )
      ? requestedSession
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
      requestedSessionId,
      fallbackSessionId: fallbackSession?.id,
    });
    const routeRetired = archivedSessionIdSet.has(requestedId);
    if (routeRetired) {
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
      // Invalidate any in-flight select for a retired id (network dedup only).
      directSessionSelectionGenerationRef.current += 1;
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
      removeSessionWorkspace(sessionId);
    });
    setSelectedAgentId((current) => current === options.agentId ? fallbackAgentId : current);
    if (archiveRouteTransition.shouldRetireRoute) {
      const nextRequestedSessionId = archiveRouteTransition.nextRequestedSessionId;
      if (nextRequestedSessionId !== requestedId) {
        // Compare-and-swap: only replace while the route still targets the archived session.
        chatRoute.replaceIfStillViewing(
          requestedId ? { kind: "session", sessionId: requestedId } : { kind: "bare" },
          nextRequestedSessionId
            ? { kind: "session", sessionId: nextRequestedSessionId }
            : { kind: "bare" },
        );
      }
    }
    setSessionComposerErrors((current) => {
      const next: Record<string, string> = { ...current, __sessions__: "" };
      archivedSessionIds.forEach((sessionId) => delete next[sessionId]);
      return next;
    });
  }, [
    chatRoute,
    clearSessionTransientUiState,
    directSessionSelectionGenerationRef,
    forgetSessionDetailPaint,
    queryClient,
    removeSessionWorkspace,
    requestedSessionId,
    retiredDirectSessionIdsRef,
    setSelectedAgentId,
    setSessionComposerErrors,
  ]);
}
