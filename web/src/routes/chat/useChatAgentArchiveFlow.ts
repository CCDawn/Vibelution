/**
 * Chat-only Agent archive: optimistic cache hide, FIFO queue, and session
 * retirement. The workbench still decides when to enqueue.
 */
import { type QueryClient } from "@tanstack/react-query";
import { type Dispatch, type MutableRefObject, type SetStateAction } from "react";

import { archiveAgent } from "../../api/agents";
import { queryKeys } from "../../api/queryKeys";
import type { AgentInstance, SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionaryTypes";
import type { AgentContextMenuState } from "../AgentContextMenu";
import type { AgentArchiveResponse } from "../agentWorkspaceCache";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";
import type { ChatRouteSelection } from "./chatSelectionProjection";
import { resolveAuthoritativeArchivedSessionIds } from "./chatSessionRouteSync";
import { describeChatRouteError as describeError } from "./chatCodingRouteViewModel";
import {
  remainingAgentsAfterConfirmedArchive,
  restoreOptimisticallyArchivedAgent,
  useChatAgentArchiveQueue,
} from "./useChatAgentArchiveQueue";
import { useChatArchivedAgentRetirement } from "./useChatArchivedAgentRetirement";

type ChatWorkspaceCache = ReturnType<typeof createChatWorkspaceCache>;

export type UseChatAgentArchiveFlowInput = {
  clearSessionTransientUiState: (sessionId: string) => void;
  directSessionSelectionGenerationRef: MutableRefObject<number>;
  forgetSessionDetailPaint: (sessionId: string) => void;
  queryClient: QueryClient;
  removeSessionWorkspace: (sessionId: string) => void;
  requestedSessionId: string | null | undefined;
  retiredDirectSessionIdsRef: MutableRefObject<ReadonlySet<string>>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setSessionComposerErrors: Dispatch<SetStateAction<Record<string, string>>>;
  replaceIfStillViewing: (expected: ChatRouteSelection, next: ChatRouteSelection) => boolean;
  sessions: SessionSummary[] | undefined;
  setAgentContextMenu: Dispatch<SetStateAction<AgentContextMenuState | null>>;
  t: (key: TranslationKey) => string;
  chatWorkspaceCache: ChatWorkspaceCache;
};

export function useChatAgentArchiveFlow({
  clearSessionTransientUiState,
  directSessionSelectionGenerationRef,
  forgetSessionDetailPaint,
  queryClient,
  removeSessionWorkspace,
  requestedSessionId,
  retiredDirectSessionIdsRef,
  setSelectedAgentId,
  setSessionComposerErrors,
  replaceIfStillViewing,
  sessions,
  setAgentContextMenu,
  t,
  chatWorkspaceCache,
}: UseChatAgentArchiveFlowInput) {
  const retireArchivedAgentSessions = useChatArchivedAgentRetirement({
    clearSessionTransientUiState,
    directSessionSelectionGenerationRef,
    forgetSessionDetailPaint,
    queryClient,
    removeSessionWorkspace,
    requestedSessionId,
    retiredDirectSessionIdsRef,
    setSelectedAgentId,
    setSessionComposerErrors,
    chatRoute: { replaceIfStillViewing },
  });

  const {
    enqueueArchive: enqueueAgentArchive,
    isAgentArchivePending,
    pendingAgentIds: pendingArchiveAgentIds,
  } = useChatAgentArchiveQueue({
    executeArchive: (agentId: string) => archiveAgent(agentId) as Promise<AgentArchiveResponse>,
    onOptimisticArchive: (agentId: string) => {
      void queryClient.cancelQueries({ queryKey: queryKeys.agents() });
      void queryClient.cancelQueries({ queryKey: queryKeys.sessions() });
      void queryClient.cancelQueries({ queryKey: queryKeys.conversations() });
      const currentAgents = queryClient.getQueryData<AgentInstance[]>(queryKeys.agents()) ?? [];
      const currentSessions = (
        queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions())
        ?? sessions
        ?? []
      );
      const archivedAgentIndex = currentAgents.findIndex((agent) => agent.agentId === agentId);
      const archivedAgent = archivedAgentIndex >= 0 ? currentAgents[archivedAgentIndex] : null;
      const remainingAgents = currentAgents.filter((agent) => agent.agentId !== agentId);
      const archivedSessionIds = currentSessions
        .filter((session) => String(session.agentId || "").trim() === agentId)
        .map((session) => session.id);

      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), remainingAgents);
      setAgentContextMenu(null);
      return {
        agent: archivedAgent,
        agentIndex: archivedAgentIndex,
        agents: currentAgents,
        sessions: currentSessions,
        optimisticArchivedSessionIds: archivedSessionIds,
      };
    },
    onArchiveSuccess: (_agentId, agent, context) => {
      const archivedSessionIds = resolveAuthoritativeArchivedSessionIds({
        optimisticSessionIds: context.optimisticArchivedSessionIds,
        archiveSummary: agent.archiveSummary,
      });
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.filter((item) => item.agentId !== agent.agentId),
      );
      // Another Agent may already be optimistically hidden while its FIFO
      // request is still pending. Keep it eligible as the semantic fallback
      // until its own archive succeeds.
      const remainingAgents = remainingAgentsAfterConfirmedArchive(context.agents, agent.agentId);
      retireArchivedAgentSessions({
        agentId: agent.agentId,
        archivedSessionIds,
        sessions: queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? context.sessions,
        remainingAgents,
      });
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: "",
      }));
    },
    onArchiveFailure: (_agentId, error, context) => {
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        restoreOptimisticallyArchivedAgent(current, {
          agent: context.agent,
          index: context.agentIndex,
        }),
      );
      setSessionComposerErrors((current) => ({
        ...current,
        __sessions__: describeError(error, t("loadFailed")),
      }));
    },
    onQueueDrained: async () => {
      try {
        await chatWorkspaceCache.afterAgentArchived();
      } catch (error) {
        setSessionComposerErrors((current) => ({
          ...current,
          __sessions__: describeError(error, t("loadFailed")),
        }));
      }
    },
  });

  return {
    enqueueAgentArchive,
    isAgentArchivePending,
    pendingArchiveAgentIds,
  };
}
