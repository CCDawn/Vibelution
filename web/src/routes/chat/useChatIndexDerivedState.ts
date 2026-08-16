import { useMemo } from "react";

import type { SessionSummary } from "../../api/types";
import { isAgentRootSession } from "../DirectSessionIndexItem";
import { shouldShowConversationIndexLoading } from "../chatSessionStartupGate";
import { isBusyPhase } from "./chatCodingRouteViewModel";
import type { SessionContextMenuState } from "./useChatSessionRenameMenu";
import type { AgentContextMenuState } from "../AgentContextMenu";

type PendingSessionMutation = {
  isPending: boolean;
  variables?: { sessionId?: string };
};

export type UseChatIndexDerivedStateInput = {
  sessionContextMenu: SessionContextMenuState | null;
  sessionsById: ReadonlyMap<string, SessionSummary>;
  deleteSessionMutation: PendingSessionMutation;
  addSessionToReviewMutation: PendingSessionMutation;
  clearSessionHistoryMutation: PendingSessionMutation;
  agentContextMenu: AgentContextMenuState | null;
  isAgentArchivePending: (agentId: string) => boolean;
  bootstrapIsLoading: boolean;
  conversationsHasData: boolean;
  conversationsIsLoading: boolean;
  sessionsHasData: boolean;
  sessionsIsLoading: boolean;
  agentsHasData: boolean;
  agentsIsLoading: boolean;
  visibleSessionCount: number;
};

export type UseChatIndexDerivedStateResult = {
  contextMenuSession: SessionSummary | undefined;
  contextMenuSessionId: string;
  contextMenuSessionIsBusy: boolean;
  contextMenuDeletePending: boolean;
  contextMenuAddToReviewPending: boolean;
  contextMenuClearHistoryPending: boolean;
  contextMenuClearHistoryVisible: boolean;
  contextMenuAgentArchivePending: boolean;
  contextMenuDeleteDisabled: boolean;
  contextMenuAddToReviewDisabled: boolean;
  contextMenuClearHistoryDisabled: boolean;
  conversationIndexLoading: boolean;
};

export function useChatIndexDerivedState({
  sessionContextMenu,
  sessionsById,
  deleteSessionMutation,
  addSessionToReviewMutation,
  clearSessionHistoryMutation,
  agentContextMenu,
  isAgentArchivePending,
  bootstrapIsLoading,
  conversationsHasData,
  conversationsIsLoading,
  sessionsHasData,
  sessionsIsLoading,
  agentsHasData,
  agentsIsLoading,
  visibleSessionCount,
}: UseChatIndexDerivedStateInput): UseChatIndexDerivedStateResult {
  const contextMenuSession = useMemo(() => {
    if (!sessionContextMenu) {
      return undefined;
    }
    return sessionsById.get(sessionContextMenu.sessionId) ?? sessionContextMenu.session;
  }, [sessionContextMenu, sessionsById]);
  const contextMenuSessionId = sessionContextMenu?.sessionId ?? "";

  const contextMenuSessionIsBusy = contextMenuSession
    ? isBusyPhase(contextMenuSession.currentPhase || contextMenuSession.status)
    : false;
  const contextMenuDeletePending = Boolean(
    contextMenuSession
    && deleteSessionMutation.isPending
    && deleteSessionMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuAddToReviewPending = Boolean(
    contextMenuSession
    && addSessionToReviewMutation.isPending
    && addSessionToReviewMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuClearHistoryPending = Boolean(
    contextMenuSession
    && clearSessionHistoryMutation.isPending
    && clearSessionHistoryMutation.variables?.sessionId === contextMenuSession.id,
  );
  const contextMenuClearHistoryVisible = Boolean(
    contextMenuSession?.agentId
    && isAgentRootSession(contextMenuSession),
  );
  const conversationIndexLoading = shouldShowConversationIndexLoading({
    bootstrapIsLoading,
    conversationsHasData,
    conversationsIsLoading,
    sessionsHasData,
    sessionsIsLoading,
    agentsHasData,
    agentsIsLoading,
    visibleSessionCount,
  });
  const contextMenuAgentArchivePending = Boolean(
    agentContextMenu
    && isAgentArchivePending(agentContextMenu.agent.agentId),
  );
  const contextMenuDeleteDisabled = contextMenuDeletePending || contextMenuSessionIsBusy;
  const contextMenuAddToReviewDisabled = contextMenuAddToReviewPending || contextMenuSessionIsBusy;
  const contextMenuClearHistoryDisabled = contextMenuClearHistoryPending || contextMenuSessionIsBusy;

  return {
    contextMenuSession,
    contextMenuSessionId,
    contextMenuSessionIsBusy,
    contextMenuDeletePending,
    contextMenuAddToReviewPending,
    contextMenuClearHistoryPending,
    contextMenuClearHistoryVisible,
    contextMenuAgentArchivePending,
    contextMenuDeleteDisabled,
    contextMenuAddToReviewDisabled,
    contextMenuClearHistoryDisabled,
    conversationIndexLoading,
  };
}
