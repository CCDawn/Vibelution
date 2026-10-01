/**
 * Memory workbench read queries (view-gated), split into core + knowledge phases.
 * Mutations stay in useMemoryItemMutations / useMemoryKnowledgeMutations.
 */
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { listAgentProjectMemoryUpdates, listAgentSummaries } from "../../api/agents";
import {
  fetchKnowledgeDashboardSnapshot,
  fetchKnowledgeGovernanceTasks,
  fetchKnowledgePermissionAudit,
  fetchKnowledgeRagHealth,
  fetchKnowledgeTrace,
  listKnowledgeCentralSources,
  listKnowledgeIngestionAdapters,
  listKnowledgeItems,
  listKnowledgeRatingSuggestions,
  listKnowledgeSourceInbox,
  retrieveKnowledgeRag,
  searchKnowledgeItems,
} from "../../api/knowledge";
import {
  fetchMemoryAgentDetail,
  fetchMemoryAgents,
  fetchMemoryKnowledgeGraph,
  fetchMemoryKnowledgeGraphNodeDetail,
  fetchMemoryOverview,
  fetchMemoryUsageContract,
  fetchGithubProjectLibrary,
} from "../../api/memory";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentInstance,
  AgentProjectMemoryUpdateProposal,
  KnowledgeCentralSourceRegistryPayload,
  KnowledgeDashboardSnapshotPayload,
  KnowledgeGovernanceTasksPayload,
  KnowledgeIngestionAdaptersPayload,
  KnowledgeItemsPayload,
  KnowledgePermissionAuditPayload,
  KnowledgeRagHealthPayload,
  KnowledgeRagRetrievalPayload,
  KnowledgeRatingSuggestionsPayload,
  KnowledgeSearchPayload,
  KnowledgeSourceInboxPayload,
  KnowledgeTracePayload,
  MemoryKnowledgeGraphNodeDetailPayload,
  MemoryKnowledgeGraphPayload,
  MemoryOverview,
  MemoryUsageContractPayload,
  GithubProjectLibraryPayload,
} from "../../api/types";
import { resolvePollingInterval } from "../../app/pollingPolicy";
import type { MemoryKnowledgeSearchDraft } from "../MemoryKnowledgeSearchPanel";
import type {
  AgentMemoryInventoryAgent,
  AgentMemoryInventoryPayload,
} from "./agentMemoryView";

import { agentMemoryDetailRevision, resolveDefaultAgentMemoryId } from "./agentMemoryView";

export type { AgentMemoryInventoryAgent, AgentMemoryInventoryPayload } from "./agentMemoryView";

const MEMORY_GRAPH_INCLUDE = "knowledge,privateMemory,officialResearchGraph";

export type MemoryRouteView =
  | "personal"
  | "team"
  | "library"
  | "graph"
  | "manage"
  | "overview"
  | "effective"
  | "agents"
  | "sources"
  | "knowledge"
  | "cleanup";

export function isPersonalMemoryView(view: MemoryRouteView) {
  return view === "personal" || view === "agents";
}

export function isTeamMemoryView(view: MemoryRouteView) {
  return view === "team" || view === "knowledge";
}

export function isLibraryMemoryView(view: MemoryRouteView) {
  return view === "library";
}

export function isManageMemoryView(view: MemoryRouteView) {
  return view === "manage" || view === "cleanup" || view === "sources" || view === "effective" || view === "overview";
}

export type MemoryProposalStatusFilter = "pending" | "";
export type RatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
export type RatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";
export type MemoryKnowledgeSourceOwnerType = "team" | "agent";

export function appendAgentParam(params: URLSearchParams, agentId: string) {
  const normalized = agentId.trim();
  if (normalized) {
    params.set("agentId", normalized);
  }
  return params;
}

export type UseMemoryCoreQueriesOptions = {
  pageVisible: boolean;
  forcedView: MemoryRouteView;
  memoryProposalStatusFilter: MemoryProposalStatusFilter;
  requestedKnowledgeActorAgentId: string;
  requestedTeamId: string;
  selectedGraphNodeId: string;
};

export function useMemoryCoreQueries(options: UseMemoryCoreQueriesOptions) {
  const {
    pageVisible,
    forcedView,
    memoryProposalStatusFilter,
    requestedKnowledgeActorAgentId,
    requestedTeamId,
    selectedGraphNodeId,
  } = options;

  // Overview payload serves two tiers. Ops views (overview/effective/manage/
  // sources/cleanup) and the library browse render item content; knowledge,
  // graph, personal/agents and team views never read sections content, so they
  // must not keep polling the full-content payload every 30s. The flag lives in
  // the queryKey (separate cache entries), so entering a content view fetches
  // the content variant immediately; non-content views skip the query entirely.
  const overviewNeedsContent = isManageMemoryView(forcedView) || isLibraryMemoryView(forcedView);
  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(overviewNeedsContent),
    queryFn: ({ signal }) => fetchMemoryOverview<MemoryOverview>({ includeContent: overviewNeedsContent, signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
    // Cache-first remount: within one poll cycle reuse the cached payload and let
    // polling refresh silently; keep the heavy content variant around 10min.
    staleTime: 30_000,
    gcTime: 600_000,
    enabled: overviewNeedsContent,
  });
  const projectMemoryUpdatesQuery = useQuery({
    queryKey: queryKeys.agentProjectMemoryUpdates(memoryProposalStatusFilter, "", 100),
    queryFn: ({ signal }) =>
      listAgentProjectMemoryUpdates({
        status: memoryProposalStatusFilter,
        limit: 100,
        signal,
      }),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
    enabled: forcedView === "overview",
  });
  const memoryUsageContractQuery = useQuery({
    queryKey: queryKeys.memoryUsageContract(),
    queryFn: ({ signal }) => fetchMemoryUsageContract<MemoryUsageContractPayload>({ signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
    enabled: forcedView === "knowledge",
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: ({ signal }) => listAgentSummaries({ signal }),
    // Personal views get both identity and selection from the memory inventory.
    enabled: isTeamMemoryView(forcedView) || forcedView === "graph" || isManageMemoryView(forcedView),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
  });
  const agentMemoryInventoryQuery = useQuery({
    queryKey: queryKeys.memoryAgentInventory(),
    queryFn: ({ signal }) => fetchMemoryAgents<AgentMemoryInventoryPayload>({ signal }),
    enabled: isPersonalMemoryView(forcedView),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
  });

  const knowledgeActorAgents = agentsQuery.data ?? [];
  const agentMemoryInventoryAgents = agentMemoryInventoryQuery.data?.agents ?? [];
  const selectedAgentMemoryAgentId = resolveDefaultAgentMemoryId(agentMemoryInventoryAgents, requestedKnowledgeActorAgentId);
  const selectedAgentMemoryInventory = agentMemoryInventoryAgents.find((agent) => agent.agentId === selectedAgentMemoryAgentId);
  const selectedAgentMemoryRevision = useMemo(
    () => agentMemoryDetailRevision(selectedAgentMemoryInventory),
    [selectedAgentMemoryInventory],
  );
  const fallbackKnowledgeActorAgentId =
    requestedKnowledgeActorAgentId
    || knowledgeActorAgents.find((agent) => agent.status !== "archived")?.agentId
    || "";

  const agentMemoryDetailQuery = useQuery({
    queryKey: queryKeys.memoryAgentDetail(selectedAgentMemoryAgentId, selectedAgentMemoryRevision),
    queryFn: ({ signal }) =>
      fetchMemoryAgentDetail<AgentMemoryInventoryPayload>(selectedAgentMemoryAgentId, {
        actorAgentId: selectedAgentMemoryAgentId,
        includeContent: true,
        signal,
      }),
    enabled: isPersonalMemoryView(forcedView) && Boolean(selectedAgentMemoryAgentId),
    refetchInterval: false,
    // Keep an open Agent's content while its new revision loads; never reuse a
    // different Agent's private body as a placeholder during selection changes.
    placeholderData: (previous) => previous?.selectedAgent?.agentId === selectedAgentMemoryAgentId ? previous : undefined,
    // Heavy includeContent payload with no polling: serve cache instantly on
    // remount and keep it parked for 15min instead of the 5min default GC.
    staleTime: 60_000,
    gcTime: 900_000,
  });
  const knowledgeDashboardSnapshotQuery = useQuery({
    queryKey: queryKeys.knowledgeDashboardSnapshot(fallbackKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      fetchKnowledgeDashboardSnapshot<KnowledgeDashboardSnapshotPayload>({
        agentId: fallbackKnowledgeActorAgentId,
        recommendationLimit: 6,
        workbenchLimit: 8,
        planLimit: 8,
        signal,
      }),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    // Large aggregated payload: cache-first remount + extended GC.
    staleTime: 45_000,
    gcTime: 600_000,
    enabled: (isTeamMemoryView(forcedView) || isManageMemoryView(forcedView)) && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, MEMORY_GRAPH_INCLUDE, requestedTeamId),
    queryFn: ({ signal }) =>
      fetchMemoryKnowledgeGraph<MemoryKnowledgeGraphPayload>({
        agentId: fallbackKnowledgeActorAgentId,
        include: MEMORY_GRAPH_INCLUDE,
        teamId: requestedTeamId || undefined,
        signal,
      }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
    enabled: forcedView === "graph" && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphNodeDetailQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      fetchMemoryKnowledgeGraphNodeDetail<MemoryKnowledgeGraphNodeDetailPayload>({
        nodeId: selectedGraphNodeId,
        agentId: fallbackKnowledgeActorAgentId,
        signal,
      }),
    refetchInterval: false,
    // Detail node payload is on-demand and heavy-ish; keep cache warm briefly.
    staleTime: 60_000,
    enabled: forcedView === "graph" && Boolean(selectedGraphNodeId) && Boolean(fallbackKnowledgeActorAgentId),
  });
  const githubProjectLibraryQuery = useQuery({
    queryKey: queryKeys.githubProjectLibrary(),
    queryFn: ({ signal }) => fetchGithubProjectLibrary<GithubProjectLibraryPayload>({ signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
    enabled: isLibraryMemoryView(forcedView),
  });

  return {
    overviewQuery,
    projectMemoryUpdatesQuery,
    memoryUsageContractQuery,
    agentsQuery,
    agentMemoryInventoryQuery,
    agentMemoryDetailQuery,
    knowledgeDashboardSnapshotQuery,
    memoryKnowledgeGraphQuery,
    memoryKnowledgeGraphNodeDetailQuery,
    githubProjectLibraryQuery,
    knowledgeActorAgents,
    agentMemoryInventoryAgents,
    selectedAgentMemoryAgentId,
    fallbackKnowledgeActorAgentId,
  };
}

export type UseMemoryKnowledgeQueriesOptions = {
  pageVisible: boolean;
  forcedView: MemoryRouteView;
  activeKnowledgeBaseForItems: string;
  activeKnowledgeActorAgentId: string;
  knowledgeSearchDraft: MemoryKnowledgeSearchDraft;
  ratingSuggestionStatus: RatingSuggestionStatusFilter;
  ratingSuggestionPriority: RatingSuggestionPriorityFilter;
  traceTargetId: string;
  sourceOwnerType: MemoryKnowledgeSourceOwnerType;
  sourceOwnerId: string;
  sourceInboxStatus: "pending" | "approved" | "rejected" | "all";
};

export function useMemoryKnowledgeQueries(options: UseMemoryKnowledgeQueriesOptions) {
  const {
    pageVisible,
    forcedView,
    activeKnowledgeBaseForItems,
    activeKnowledgeActorAgentId,
    knowledgeSearchDraft,
    ratingSuggestionStatus,
    ratingSuggestionPriority,
    traceTargetId,
    sourceOwnerType,
    sourceOwnerId,
    sourceInboxStatus,
  } = options;
  const activeSourceOwnerId = sourceOwnerId.trim();
  const activeSourceInboxStatus = sourceInboxStatus === "all" ? "" : sourceInboxStatus;

  const knowledgeItemsQuery = useQuery({
    queryKey: queryKeys.knowledgeItems(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      listKnowledgeItems<KnowledgeItemsPayload>(activeKnowledgeBaseForItems, {
        agentId: activeKnowledgeActorAgentId,
        signal,
      }),
    enabled: isTeamMemoryView(forcedView) && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
  });
  const knowledgeSearchQuery = useQuery({
    queryKey: queryKeys.knowledgeSearch(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      knowledgeSearchDraft.query,
      knowledgeSearchDraft.tags,
      knowledgeSearchDraft.searchMode,
    ),
    queryFn: ({ signal }) =>
      searchKnowledgeItems<KnowledgeSearchPayload>({
        agentId: activeKnowledgeActorAgentId,
        knowledgeBaseId: activeKnowledgeBaseForItems || undefined,
        query: knowledgeSearchDraft.query,
        tags: knowledgeSearchDraft.tags,
        searchMode: knowledgeSearchDraft.searchMode,
        limit: 12,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: false,
  });
  const knowledgeRagHealthQuery = useQuery({
    queryKey: queryKeys.knowledgeRagHealth(activeKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      fetchKnowledgeRagHealth<KnowledgeRagHealthPayload>({
        agentId: activeKnowledgeActorAgentId,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
  });
  const knowledgeRagRetrieveQuery = useQuery({
    queryKey: queryKeys.knowledgeRagRetrieve(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      knowledgeSearchDraft.query,
      knowledgeSearchDraft.tags,
      knowledgeSearchDraft.searchMode,
      knowledgeSearchDraft.ragTopK,
      knowledgeSearchDraft.ragMaxContextChars,
    ),
    queryFn: ({ signal }) =>
      retrieveKnowledgeRag<KnowledgeRagRetrievalPayload>({
        agentId: activeKnowledgeActorAgentId,
        knowledgeBaseId: activeKnowledgeBaseForItems || undefined,
        query: knowledgeSearchDraft.query,
        tags: knowledgeSearchDraft.tags,
        retrievalMode: knowledgeSearchDraft.searchMode,
        provider: "local",
        topK: knowledgeSearchDraft.ragTopK,
        maxContextChars: knowledgeSearchDraft.ragMaxContextChars,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: false,
  });
  const ratingSuggestionsQuery = useQuery({
    queryKey: queryKeys.knowledgeRatingSuggestions(
      activeKnowledgeBaseForItems,
      activeKnowledgeActorAgentId,
      ratingSuggestionStatus,
      ratingSuggestionPriority,
    ),
    queryFn: ({ signal }) =>
      listKnowledgeRatingSuggestions<KnowledgeRatingSuggestionsPayload>(activeKnowledgeBaseForItems, {
        agentId: activeKnowledgeActorAgentId,
        status: ratingSuggestionStatus === "all" ? undefined : ratingSuggestionStatus,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
  });
  const permissionAuditQuery = useQuery({
    queryKey: queryKeys.knowledgePermissionAudit(activeKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      fetchKnowledgePermissionAudit<KnowledgePermissionAuditPayload>({
        agentId: activeKnowledgeActorAgentId,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
  });
  const governanceTasksQuery = useQuery({
    queryKey: queryKeys.knowledgeGovernanceTasks(activeKnowledgeActorAgentId, "open"),
    queryFn: ({ signal }) =>
      fetchKnowledgeGovernanceTasks<KnowledgeGovernanceTasksPayload>({
        agentId: activeKnowledgeActorAgentId,
        status: "open",
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
  });
  const ingestionAdaptersQuery = useQuery({
    queryKey: queryKeys.knowledgeIngestionAdapters(),
    queryFn: ({ signal }) => listKnowledgeIngestionAdapters<KnowledgeIngestionAdaptersPayload>({ signal }),
    enabled: forcedView === "knowledge",
    refetchInterval: false,
  });
  const knowledgeTraceQuery = useQuery({
    queryKey: queryKeys.knowledgeTrace(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId, traceTargetId),
    queryFn: ({ signal }) =>
      fetchKnowledgeTrace<KnowledgeTracePayload>(activeKnowledgeBaseForItems, traceTargetId, {
        agentId: activeKnowledgeActorAgentId,
        signal,
      }),
    enabled:
      forcedView === "knowledge"
      && Boolean(activeKnowledgeBaseForItems)
      && Boolean(activeKnowledgeActorAgentId)
      && Boolean(traceTargetId),
    refetchInterval: false,
  });
  const sourceInboxQuery = useQuery({
    queryKey: queryKeys.knowledgeSourceInbox(
      sourceOwnerType,
      activeSourceOwnerId,
      activeKnowledgeActorAgentId,
      activeSourceInboxStatus,
    ),
    queryFn: ({ signal }) =>
      listKnowledgeSourceInbox<KnowledgeSourceInboxPayload>({
        ownerType: sourceOwnerType,
        ownerId: activeSourceOwnerId,
        agentId: activeKnowledgeActorAgentId,
        status: activeSourceInboxStatus || undefined,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeSourceOwnerId) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    staleTime: 45_000,
  });
  const centralSourcesQuery = useQuery({
    queryKey: queryKeys.knowledgeCentralSources(activeKnowledgeActorAgentId, sourceOwnerType, activeSourceOwnerId),
    queryFn: ({ signal }) =>
      listKnowledgeCentralSources<KnowledgeCentralSourceRegistryPayload>({
        agentId: activeKnowledgeActorAgentId,
        ownerType: sourceOwnerType,
        ownerId: activeSourceOwnerId,
        signal,
      }),
    enabled: forcedView === "knowledge" && Boolean(activeSourceOwnerId) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    staleTime: 60_000,
  });
  return {
    knowledgeItemsQuery,
    knowledgeSearchQuery,
    knowledgeRagHealthQuery,
    knowledgeRagRetrieveQuery,
    ratingSuggestionsQuery,
    permissionAuditQuery,
    governanceTasksQuery,
    ingestionAdaptersQuery,
    knowledgeTraceQuery,
    sourceInboxQuery,
    centralSourcesQuery,
  };
}
