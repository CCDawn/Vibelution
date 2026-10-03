/**
 * Chat workbench catalog / secondary data queries (R01c).
 * Owns runtime/pet/config/session-index/conversations/teams/agents/skills/
 * chat-room catalog and expanded agent detail windows — not session detail SSE.
 */

import { useInfiniteQuery, useQueries, useQuery, type InfiniteData, type QueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";

import { listAgentSummaries } from "../../api/agents";
import {
  fetchChatRoomDetail,
  fetchChatWorkbenchBootstrap,
  listChatRoomModes,
  listChatRoomPurposes,
  queryConversations,
} from "../../api/chat";
import { fetchPublicConfig } from "../../api/config";
import { listProjectAgentBusTimeline } from "../../api/projectAgentBus";
import { fetchRuntimeSummary } from "../../api/runtime";
import { listArchivedChatSessions } from "../../api/sessionArchive";
import { fetchSkillLibrary } from "../../api/skills";
import { listTeams } from "../../api/teams";
import { queryKeys } from "../../api/queryKeys";
import type {
  ConversationQueryResponse,
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

/**
 * The unified catalog poll keeps only the group-room half of the conversation
 * index: direct conversations are projected from the session index query plus
 * the agent directory merge, so polling them duplicated ~90% of the payload.
 * Measured against a 144-item index (130 sessions / 14 rooms): full pull
 * ~195 KB across 2 requests vs ~16 KB for this group-room page.
 */
const CONVERSATIONS_CATALOG_PAGE_SIZE = 100;

/**
 * While the backend reports the directory store as mid-startup, poll the cheap
 * bootstrap endpoint for the flipped bit instead of firing session queries that
 * can only receive the startup empty page.
 */
const DIRECTORY_READY_POLL_MS = 1_000;
/** Bounded fallback so a wedged directory startup can never gate the list forever. */
const DIRECTORY_READY_WAIT_TIMEOUT_MS = 20_000;

export type ChatWorkbenchCatalogQueriesInput = {
  queryClient: QueryClient;
  secondaryChatDataEnabled: boolean;
  chatSecondaryPollPolicy: ChatSecondaryPollPolicy;
  chatLiveQueryPolicy: ChatLiveQueryPolicy;
  sessionQueryText: string;
  /** Session index sort (backend whitelist value); empty keeps the default. */
  sessionListSort?: string;
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
  /** Archived view toggle: lazily fetches the archived-session listing. */
  showArchivedSessions: boolean;
};

export function useChatWorkbenchCatalogQueries(input: ChatWorkbenchCatalogQueriesInput) {
  const {
    queryClient,
    secondaryChatDataEnabled,
    chatSecondaryPollPolicy,
    chatLiveQueryPolicy,
    sessionQueryText,
    sessionListSort = "",
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
    queryFn: ({ signal }) => fetchRuntimeSummary({ signal }),
    enabled: secondaryChatDataEnabled,
    refetchInterval: chatSecondaryPollPolicy.runtimeRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
    structuralSharing: shareRuntimeSummaryIfOnlyVolatileChanged,
  });
  const configSummaryQuery = useQuery({
    queryKey: queryKeys.configPublic(),
    queryFn: ({ signal }) => fetchPublicConfig({ signal }),
    staleTime: 30_000,
  });
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [directoryReadyWaitExpired, setDirectoryReadyWaitExpired] = useState(false);
  const activeSessionBootstrapQuery = useQuery({
    queryKey: ["sessions", "active-bootstrap"],
    queryFn: async ({ signal }) => {
      const payload = await fetchChatWorkbenchBootstrap({ signal });
      signal.throwIfAborted();
      queryClient.setQueryData(queryKeys.agents(), payload.agents);
      // Seed the group-room catalog with the bootstrap projection so the rail
      // paints before the paginated catalog query resolves; the catalog query
      // reconciles (and continues paging) right after.
      queryClient.setQueryData<InfiniteData<ConversationQueryResponse, string>>(
        queryKeys.conversationsCatalogQuery(CONVERSATIONS_CATALOG_PAGE_SIZE),
        (existing) => existing ?? {
          pages: [{
            items: payload.conversations,
            nextCursor: "",
            totalEstimate: payload.conversations.length,
            filters: { q: "", agentId: "", teamId: "", type: "group_room", sort: "updatedAt_desc", limit: CONVERSATIONS_CATALOG_PAGE_SIZE, cursor: "" },
          }],
          pageParams: [""],
        },
      );
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
    // Re-check the directory ready bit while the backend store is mid-startup;
    // once it flips (or the payload omits it), this stops polling on its own.
    refetchInterval: (query) =>
      query.state.data?.directoryReady === false ? DIRECTORY_READY_POLL_MS : false,
  });
  const bootstrapSettled = activeSessionBootstrapQuery.isFetched || activeSessionBootstrapQuery.isError;
  const bootstrapDirectoryReady = activeSessionBootstrapQuery.data?.directoryReady !== false;
  // Bounded fallback: if the directory never reports ready, open the gate so the
  // index recovers through the normal poll cycle instead of waiting forever.
  useEffect(() => {
    if (bootstrapDirectoryReady || activeSessionBootstrapQuery.isError || directoryReadyWaitExpired) {
      return;
    }
    const timer = window.setTimeout(
      () => setDirectoryReadyWaitExpired(true),
      DIRECTORY_READY_WAIT_TIMEOUT_MS,
    );
    return () => window.clearTimeout(timer);
  }, [bootstrapDirectoryReady, activeSessionBootstrapQuery.isError, directoryReadyWaitExpired]);
  const directoryGatePending = !bootstrapDirectoryReady && !directoryReadyWaitExpired;
  // Prefer URL targets immediately. If the bootstrap is cancelled or fails, let
  // the canonical session index recover instead of leaving the directory gated.
  const sessionIndexQueryEnabled = shouldEnableSessionIndexQuery({
    hasRouteTarget: Boolean(input.requestedSessionId || input.requestedRoomId),
    hasActiveSession: Boolean(activeSessionId),
    bootstrapIsFetched: activeSessionBootstrapQuery.isFetched,
    bootstrapIsError: activeSessionBootstrapQuery.isError,
    bootstrapFetchStatus: activeSessionBootstrapQuery.fetchStatus,
    directoryReady: bootstrapDirectoryReady,
    directoryReadyWaitExpired,
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
    sort: sessionListSort,
  });
  const visibleSessionsData = useMemo(
    () => rawSessionsQuery.data?.filter((session) => isVisibleDirectSession(session)),
    [rawSessionsQuery.data],
  );
  const sessionsQuery = useMemo(
    () => ({
      ...rawSessionsQuery,
      data: visibleSessionsData,
    }),
    [rawSessionsQuery, visibleSessionsData],
  );
  const archivedSessionsQuery = useQuery({
    queryKey: queryKeys.sessionArchive(),
    queryFn: ({ signal }) => listArchivedChatSessions({ signal }),
    enabled: input.showArchivedSessions,
    staleTime: 5_000,
  });
  const conversationsQueryRaw = useInfiniteQuery({
    queryKey: queryKeys.conversationsCatalogQuery(CONVERSATIONS_CATALOG_PAGE_SIZE),
    initialPageParam: "",
    enabled: secondaryChatDataEnabled && bootstrapSettled,
    staleTime: 5_000,
    refetchInterval: chatLiveQueryPolicy.conversationsRefetchInterval,
    refetchIntervalInBackground: chatLiveQueryPolicy.sharedRefetchIntervalInBackground,
    queryFn: async ({ pageParam, signal }) => {
      const payload = await queryConversations({
        limit: CONVERSATIONS_CATALOG_PAGE_SIZE,
        cursor: String(pageParam || ""),
        type: "group_room",
      }, { signal });
      return {
        ...payload,
        items: filterOutTombstonedConversations(payload.items) ?? [],
      };
    },
    getNextPageParam: (lastPage) => lastPage.nextCursor || undefined,
  });
  // The rail renders every team room, so exhaust the cursor like the session
  // index does instead of stopping at the first catalog page.
  useEffect(() => {
    if (!conversationsQueryRaw.hasNextPage || conversationsQueryRaw.isFetchingNextPage) {
      return;
    }
    void conversationsQueryRaw.fetchNextPage();
  }, [
    conversationsQueryRaw.hasNextPage,
    conversationsQueryRaw.isFetchingNextPage,
    conversationsQueryRaw.fetchNextPage,
  ]);
  const conversationsQuery = useMemo(() => {
    const data = filterOutTombstonedConversations(
      conversationsQueryRaw.data?.pages.flatMap((page) => page.items ?? []),
    );
    const lastPage = conversationsQueryRaw.data?.pages.at(-1);
    return {
      data,
      dataUpdatedAt: conversationsQueryRaw.dataUpdatedAt,
      error: conversationsQueryRaw.error,
      isError: conversationsQueryRaw.isError,
      isFetching: conversationsQueryRaw.isFetching,
      isLoading: conversationsQueryRaw.isLoading,
      refetch: conversationsQueryRaw.refetch,
      totalEstimate:
        typeof lastPage?.totalEstimate === "number"
          ? lastPage.totalEstimate
          : (data?.length ?? 0),
    };
  }, [conversationsQueryRaw]);
  const teamsQuery = useQuery({
    queryKey: queryKeys.teams(),
    queryFn: ({ signal }) => listTeams({ signal }),
    // Must load whenever the left-rail agent directory is active — not only when the
    // group-room picker is open. With teams=[], research/evolution members all dump into
    // 「特殊 Agent」and team rooms fall into 未归属.
    enabled: secondaryChatDataEnabled || sessionIndexQueryEnabled,
    refetchInterval: chatSecondaryPollPolicy.teamsRefetchInterval,
    refetchIntervalInBackground: chatSecondaryPollPolicy.secondaryRefetchIntervalInBackground,
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: ({ signal }) => listAgentSummaries({ signal }),
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
  /**
   * Slash panel catalog state (ZCode slashCommandPanelSections parity): the
   * panel renders loading/error placeholders for the skills section instead of
   * silently showing an empty list when the skill library query fails.
   */
  const slashSkillsCatalogState: "ready" | "loading" | "error" = skillsQuery.isError
    ? "error"
    : skillsQuery.isPending
      ? "loading"
      : "ready";
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
    queryFn: ({ signal }) => fetchChatRoomDetail(activeGroupRoomId, { signal }),
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
      queryFn: ({ signal }: { signal: AbortSignal }) => fetchSessionDetailWindow(sessionId, { messageLimit: 20, signal }),
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
    configSummaryQuery,
    selectedAgentId,
    setSelectedAgentId,
    activeSessionBootstrapQuery,
    sessionIndexQueryEnabled,
    directoryGatePending,
    modelLabelsById,
    modelImageInputSupportById,
    resolveModelLabel,
    rawSessionsQuery,
    sessionsQuery,
    archivedSessionsQuery,
    conversationsQuery,
    teamsQuery,
    agentsQuery,
    skillsQuery,
    slashCommandSuggestions,
    slashSkillsCatalogState,
    chatRoomModesQuery,
    chatRoomPurposesQuery,
    activeGroupRoomQuery,
    projectAgentBusQuery,
    expandedGroupAgentDetailQueries,
  };
}
