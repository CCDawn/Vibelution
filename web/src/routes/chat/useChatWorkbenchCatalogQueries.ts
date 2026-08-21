/**
 * Chat workbench catalog / secondary data queries (R01c).
 * Owns runtime/pet/config/session-index/conversations/teams/agents/skills/
 * chat-room catalog and expanded agent detail windows — not session detail SSE.
 */

import { useQueries, useQuery, type QueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";

import { listAgentSummaries } from "../../api/agents";
import {
  fetchChatRoomDetail,
  fetchChatWorkbenchBootstrap,
  listChatRoomModes,
  listChatRoomPurposes,
  listConversations,
} from "../../api/chat";
import { fetchPublicConfig } from "../../api/config";
import { fetchPetSummary } from "../../api/pet";
import { listProjectAgentBusTimeline } from "../../api/projectAgentBus";
import { fetchRuntimeSummary } from "../../api/runtime";
import { fetchSkillLibrary } from "../../api/skills";
import { listTeams } from "../../api/teams";
import { queryKeys } from "../../api/queryKeys";
import type {
  SessionSummary,
} from "../../api/types";
import { resolvePollingInterval } from "../../app/pollingPolicy";
import { shareRuntimeSummaryIfOnlyVolatileChanged } from "../../app/runtimeSummaryQueryShare";
import {
  ACTIVE_BACKGROUND_SYNC_POLL_MS,
  type ChatLiveQueryPolicy,
} from "../chatLiveQueryPolicy";
import type { ChatSecondaryPollPolicy } from "../chatSecondaryPollPolicy";
import { useSessionIndexQuery } from "../chatSessionIndexQuery";
import { shouldEnableSessionIndexQuery } from "../chatSessionStartupGate";
import { isVisibleDirectSession } from "../conversationIndexModel";
import { mergePreservedCreatedSessions } from "../sessionCreatePreserve";
import { filterOutTombstonedConversations } from "../sessionDeleteTombstone";
import { fetchSessionDetailWindow } from "./chatSessionDetailHelpers";

export type ChatWorkbenchCatalogQueriesInput = {
  queryClient: QueryClient;
  secondaryChatDataEnabled: boolean;
  chatSecondaryPollPolicy: ChatSecondaryPollPolicy;
  chatLiveQueryPolicy: ChatLiveQueryPolicy;
  sessionQueryText: string;
  activeSessionId: string;
  activeGroupRoomId: string;
  expandedGroupAgentSessionIds: string[];
  groupComposerOpen: boolean;
  standardGroupRoomActive: boolean;
  projectBusActive: boolean;
  chatPollingVisible: boolean;
  chatStartupWarmupActive: boolean;
  groupBackgroundSyncActive: boolean;
  groupStreamConnected: boolean;
  requestedSessionId: string;
  requestedRoomId: string;
};

export function useChatWorkbenchCatalogQueries(input: ChatWorkbenchCatalogQueriesInput) {
  const {
    queryClient,
    secondaryChatDataEnabled,
    chatSecondaryPollPolicy,
    chatLiveQueryPolicy,
    sessionQueryText,
    activeSessionId,
    activeGroupRoomId,
    expandedGroupAgentSessionIds,
    groupComposerOpen,
    standardGroupRoomActive,
    projectBusActive,
    chatPollingVisible,
    chatStartupWarmupActive,
    groupBackgroundSyncActive,
    groupStreamConnected,
  } = input;

  const runtimeQuery = useQuery({
    queryKey: queryKeys.runtimeSummary(),
    queryFn: () => fetchRuntimeSummary(),
    enabled: secondaryChatDataEnabled,
    refetchInterval: chatSecondaryPollPolicy.runtimeRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
    structuralSharing: shareRuntimeSummaryIfOnlyVolatileChanged,
  });
  const petQuery = useQuery({
    queryKey: queryKeys.petSummary(),
    queryFn: () => fetchPetSummary(),
    enabled: secondaryChatDataEnabled,
    refetchInterval: chatSecondaryPollPolicy.petRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: () => fetchPublicConfig(),
    staleTime: 30_000,
  });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const activeSessionBootstrapQuery = useQuery({
    queryKey: ["sessions", "active-bootstrap"],
    queryFn: async ({ signal }) => {
      const payload = await fetchChatWorkbenchBootstrap({ signal });
      queryClient.setQueryData(queryKeys.agents(), payload.agents);
      queryClient.setQueryData(queryKeys.conversations(), payload.conversations);
      // Never hard-replace the session index page: create optimism / pins must
      // survive bootstrap refetch triggered by broad `["sessions"]` invalidation.
      const previous = queryClient.getQueryData<{
        pages: Array<{ items?: SessionSummary[] }>;
        pageParams: unknown[];
      }>(queryKeys.sessionQuery("", 50));
      const previousItems = previous?.pages.flatMap((page) => page.items ?? []) ?? [];
      const mergedItems = mergePreservedCreatedSessions(payload.sessionPage?.items ?? [], {
        localItems: previousItems,
      });
      const mergedPage = {
        ...payload.sessionPage,
        items: mergedItems,
      };
      queryClient.setQueryData(
        queryKeys.sessionQuery("", 50),
        { pages: [mergedPage], pageParams: [""] },
      );
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (existing) =>
        mergePreservedCreatedSessions(mergedItems, { localItems: existing ?? previousItems }),
      );
      return {
        ...payload,
        sessionPage: mergedPage,
      };
    },
    staleTime: 5_000,
  });
  const bootstrapSettled = activeSessionBootstrapQuery.isFetched || activeSessionBootstrapQuery.isError;
  // Prefer URL targets immediately. If the bootstrap is cancelled or fails, let
  // the canonical session index recover instead of leaving the directory gated.
  const sessionIndexQueryEnabled = shouldEnableSessionIndexQuery({
    hasRouteTarget: Boolean(input.requestedSessionId || input.requestedRoomId),
    hasActiveSession: Boolean(activeSessionId),
    bootstrapIsFetched: activeSessionBootstrapQuery.isFetched,
    bootstrapIsError: activeSessionBootstrapQuery.isError,
    bootstrapFetchStatus: activeSessionBootstrapQuery.fetchStatus,
  });
  const modelLabelsById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelLabels ?? {})),
    [configSummaryQuery.data?.modelLabels],
  );
  const modelImageInputSupportById = useMemo(
    () => new Map(Object.entries(configSummaryQuery.data?.modelImageInputSupport ?? {})),
    [configSummaryQuery.data?.modelImageInputSupport],
  );
  const resolveModelLabel = useCallback(
    (modelId: string) => modelLabelsById.get(modelId),
    [modelLabelsById],
  );
  const rawSessionsQuery = useSessionIndexQuery({
    queryClient,
    queryText: sessionQueryText,
    enabled: sessionIndexQueryEnabled,
    refetchInterval: chatLiveQueryPolicy.sessionsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.directRefetchIntervalInBackground,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter(isVisibleDirectSession),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = useMemo(
    () => ({
      ...rawSessionsQuery,
      data: visibleSessionsData,
    }),
    [rawSessionsQuery, visibleSessionsData],
  );
  const conversationsQueryRaw = useQuery({
    queryKey: queryKeys.conversations(),
    queryFn: () => listConversations(),
    enabled: secondaryChatDataEnabled && bootstrapSettled,
    staleTime: 5_000,
    refetchInterval: chatLiveQueryPolicy.conversationsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.sharedRefetchIntervalInBackground,
  });
  const conversationsQuery = useMemo(() => {
    const data = filterOutTombstonedConversations(conversationsQueryRaw.data);
    return {
      ...conversationsQueryRaw,
      data,
    };
  }, [conversationsQueryRaw]);
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: () => listTeams(),
    // Must load whenever the left-rail agent directory is active — not only when the
    // group-room picker is open. With teams=[], research/evolution members all dump into
    // 「特殊 Agent」and team rooms fall into 未归属.
    enabled: secondaryChatDataEnabled || sessionIndexQueryEnabled,
    refetchInterval: chatSecondaryPollPolicy.teamsRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => listAgentSummaries(),
    enabled:
      bootstrapSettled &&
      (secondaryChatDataEnabled || sessionIndexQueryEnabled || groupComposerOpen || standardGroupRoomActive),
    staleTime: 5_000,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills(),
    queryFn: () => fetchSkillLibrary(),
    enabled: secondaryChatDataEnabled && Boolean(activeSessionId),
    staleTime: 60_000,
  });
  const slashCommandSuggestions = skillsQuery.data?.skills ?? [];
  const chatRoomModesQuery = useQuery({
    queryKey: queryKeys.chatRoomModes(),
    queryFn: () => listChatRoomModes(),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const chatRoomPurposesQuery = useQuery({
    queryKey: queryKeys.chatRoomPurposes(),
    queryFn: () => listChatRoomPurposes(),
    enabled: groupComposerOpen || standardGroupRoomActive,
  });
  const activeGroupRoomQuery = useQuery({
    queryKey: queryKeys.chatRoom(activeGroupRoomId || "none"),
    queryFn: () => fetchChatRoomDetail(activeGroupRoomId),
    enabled: standardGroupRoomActive,
    refetchInterval: standardGroupRoomActive
      ? resolvePollingInterval(
          chatPollingVisible,
          groupStreamConnected ? false : 3_000,
          { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
        )
      : false,
    refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
  });
  const projectAgentBusQuery = useQuery({
    queryKey: queryKeys.projectAgentBus(),
    queryFn: ({ signal }) => listProjectAgentBusTimeline(undefined, { signal }),
    enabled: projectBusActive,
    refetchInterval: chatSecondaryPollPolicy.projectBusRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
  });
  const expandedGroupAgentDetailQueries = useQueries({
    queries: expandedGroupAgentSessionIds.map((sessionId) => ({
      queryKey: queryKeys.groupExpandedSession(sessionId || "none"),
      queryFn: () => fetchSessionDetailWindow(sessionId, { messageLimit: 20 }),
      enabled: standardGroupRoomActive && Boolean(sessionId),
      // Match group room detail: only poll while SSE is not open (F2).
      refetchInterval: standardGroupRoomActive && sessionId
        ? resolvePollingInterval(
            chatPollingVisible,
            groupStreamConnected ? false : 3_000,
            { backgroundMs: groupBackgroundSyncActive && !groupStreamConnected ? ACTIVE_BACKGROUND_SYNC_POLL_MS : false },
          )
        : false,
      refetchIntervalInBackground: chatStartupWarmupActive || groupBackgroundSyncActive,
    })),
  });

  return {
    runtimeQuery,
    petQuery,
    configSummaryQuery,
    selectedAgentId,
    setSelectedAgentId,
    activeSessionBootstrapQuery,
    sessionIndexQueryEnabled,
    modelLabelsById,
    modelImageInputSupportById,
    resolveModelLabel,
    rawSessionsQuery,
    sessionsQuery,
    conversationsQuery,
    teamsQuery,
    agentsQuery,
    skillsQuery,
    slashCommandSuggestions,
    chatRoomModesQuery,
    chatRoomPurposesQuery,
    activeGroupRoomQuery,
    projectAgentBusQuery,
    expandedGroupAgentDetailQueries,
  };
}
