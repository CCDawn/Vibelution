/**
 * Memory workbench read queries (view-gated), split into core + knowledge phases.
 * Mutations stay in useMemoryItemMutations / useMemoryKnowledgeMutations.
 */
import { useQuery } from "@tanstack/react-query";

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
} from "../../api/types";
import { resolvePollingInterval } from "../../app/pollingPolicy";
import type { MemoryKnowledgeSearchDraft } from "../MemoryKnowledgeSearchPanel";

export type MemoryRouteView =
  | "overview"
  | "effective"
  | "agents"
  | "manage"
  | "sources"
  | "knowledge"
  | "graph"
  | "cleanup";

export type MemoryProposalStatusFilter = "pending" | "";
export type RatingSuggestionStatusFilter = "pending" | "applied" | "rejected" | "all";
export type RatingSuggestionPriorityFilter = "all" | "urgent" | "elevated" | "normal";
export type MemoryKnowledgeSourceOwnerType = "team" | "agent";

export type AgentMemoryInventoryAgent = {
  agentId: string;
  displayName?: string;
  agentCode?: string;
  status?: string;
  hasPrivateMemory?: boolean;
  workspacePath?: string;
  privateMemoryRoot?: string;
  privateFileCount?: number;
  formalKnowledgeBaseCount?: number;
  origin?: string;
  primaryMode?: string;
  roleKey?: string;
  items?: Array<{
    id: string;
    relativePath?: string;
    title?: string;
    updatedAt?: string;
    path?: string;
    summary?: string;
    sizeBytes?: number;
    contentType?: string;
    contentTruncated?: boolean;
    content?: string;
  }>;
};

export type AgentMemoryInventoryPayload = {
  agents?: AgentMemoryInventoryAgent[];
  summary?: {
    agentCount?: number;
    privateFileCount?: number;
    privateByteCount?: number;
    formalKnowledgeItemCount?: number;
    formalKnowledgeBaseCount?: number;
    warningCount?: number;
  };
  generatedAt?: string;
  selectedAgent?: AgentMemoryInventoryAgent | null;
};


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

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: ({ signal }) => fetchMemoryOverview<MemoryOverview>({ includeContent: false, signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
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
    enabled: forcedView === "overview",
  });
  const memoryUsageContractQuery = useQuery({
    queryKey: queryKeys.memoryUsageContract(),
    queryFn: ({ signal }) => fetchMemoryUsageContract<MemoryUsageContractPayload>({ signal }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "knowledge",
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: ({ signal }) => listAgentSummaries({ signal }),
    enabled: forcedView === "agents" || forcedView === "knowledge" || forcedView === "graph" || forcedView === "cleanup",
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const agentMemoryInventoryQuery = useQuery({
    queryKey: ["memory", "agents", "inventory"],
    queryFn: ({ signal }) => fetchMemoryAgents<AgentMemoryInventoryPayload>({ signal }),
    enabled: forcedView === "agents",
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });

  const knowledgeActorAgents = agentsQuery.data ?? [];
  const agentMemoryInventoryAgents = agentMemoryInventoryQuery.data?.agents ?? [];
  const requestedAgentMemoryAgent = requestedKnowledgeActorAgentId
    ? agentMemoryInventoryAgents.find((agent) => agent.agentId === requestedKnowledgeActorAgentId) ?? null
    : null;
  const selectedAgentMemoryAgentId =
    requestedAgentMemoryAgent?.agentId
    || agentMemoryInventoryAgents.find((agent) => agent.hasPrivateMemory)?.agentId
    || agentMemoryInventoryAgents.find((agent) => agent.status !== "archived")?.agentId
    || agentMemoryInventoryAgents[0]?.agentId
    || "";
  const fallbackKnowledgeActorAgentId =
    requestedKnowledgeActorAgentId
    || knowledgeActorAgents.find((agent) => agent.status !== "archived")?.agentId
    || "";

  const agentMemoryDetailQuery = useQuery({
    queryKey: ["memory", "agents", selectedAgentMemoryAgentId, "detail"],
    queryFn: ({ signal }) =>
      fetchMemoryAgentDetail<AgentMemoryInventoryPayload>(selectedAgentMemoryAgentId, {
        actorAgentId: selectedAgentMemoryAgentId,
        signal,
      }),
    enabled: forcedView === "agents" && Boolean(selectedAgentMemoryAgentId),
    refetchInterval: false,
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
    enabled: (forcedView === "knowledge" || forcedView === "cleanup") && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId),
    queryFn: ({ signal }) =>
      fetchMemoryKnowledgeGraph<MemoryKnowledgeGraphPayload>({
        agentId: fallbackKnowledgeActorAgentId,
        include: "officialResearchGraph",
        teamId: requestedTeamId || undefined,
        signal,
      }),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
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
    enabled: forcedView === "graph" && Boolean(selectedGraphNodeId) && Boolean(fallbackKnowledgeActorAgentId),
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
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
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
