/**
 * Memory workbench read queries (view-gated), split into core + knowledge phases.
 * Mutations stay in useMemoryItemMutations / useMemoryKnowledgeMutations.
 */
import { useQuery } from "@tanstack/react-query";

import { listAgentProjectMemoryUpdates, listAgentSummaries } from "../../api/agents";
import { fetchJson } from "../../api/client";
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

function commaList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
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
    queryFn: ({ signal }) => fetchJson<MemoryOverview>("/api/memory/overview?includeContent=false", { signal }),
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
    queryFn: ({ signal }) => fetchJson<MemoryUsageContractPayload>("/api/memory/usage-contract", { signal }),
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
    queryFn: ({ signal }) => fetchJson<AgentMemoryInventoryPayload>("/api/memory/agents", { signal }),
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
      fetchJson<AgentMemoryInventoryPayload>(
        `/api/memory/agents/${encodeURIComponent(selectedAgentMemoryAgentId)}?actorAgentId=${encodeURIComponent(selectedAgentMemoryAgentId)}`,
        { signal },
      ),
    enabled: forcedView === "agents" && Boolean(selectedAgentMemoryAgentId),
    refetchInterval: false,
  });
  const knowledgeDashboardSnapshotQuery = useQuery({
    queryKey: queryKeys.knowledgeDashboardSnapshot(fallbackKnowledgeActorAgentId),
    queryFn: ({ signal }) => {
      const params = appendAgentParam(
        new URLSearchParams({
          recommendationLimit: "6",
          workbenchLimit: "8",
          planLimit: "8",
        }),
        fallbackKnowledgeActorAgentId,
      );
      return fetchJson<KnowledgeDashboardSnapshotPayload>(
        `/api/knowledge/dashboard-snapshot?${params.toString()}`,
        { signal },
      );
    },
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
    enabled: (forcedView === "knowledge" || forcedView === "cleanup") && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraph(fallbackKnowledgeActorAgentId, "officialResearchGraph", requestedTeamId),
    queryFn: ({ signal }) => {
      const params = appendAgentParam(
        new URLSearchParams({ include: "officialResearchGraph" }),
        fallbackKnowledgeActorAgentId,
      );
      if (requestedTeamId) {
        params.set("teamId", requestedTeamId);
      }
      return fetchJson<MemoryKnowledgeGraphPayload>(`/api/memory/knowledge-graph?${params.toString()}`, { signal });
    },
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
    enabled: forcedView === "graph" && Boolean(fallbackKnowledgeActorAgentId),
  });
  const memoryKnowledgeGraphNodeDetailQuery = useQuery({
    queryKey: queryKeys.memoryKnowledgeGraphNodeDetail(selectedGraphNodeId, fallbackKnowledgeActorAgentId),
    queryFn: ({ signal }) => {
      const params = appendAgentParam(new URLSearchParams({ nodeId: selectedGraphNodeId }), fallbackKnowledgeActorAgentId);
      return fetchJson<MemoryKnowledgeGraphNodeDetailPayload>(
        `/api/memory/knowledge-graph/node-detail?${params.toString()}`,
        { signal },
      );
    },
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
    queryFn: ({ signal }) => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeItemsPayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/items?${params.toString()}`,
        { signal },
      );
    },
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
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      params.set("agentId", activeKnowledgeActorAgentId);
      if (activeKnowledgeBaseForItems) {
        params.set("knowledgeBaseId", activeKnowledgeBaseForItems);
      }
      if (knowledgeSearchDraft.query.trim()) {
        params.set("query", knowledgeSearchDraft.query.trim());
      }
      commaList(knowledgeSearchDraft.tags).forEach((tag) => params.append("tags", tag));
      params.set("searchMode", knowledgeSearchDraft.searchMode);
      params.set("limit", "12");
      return fetchJson<KnowledgeSearchPayload>(`/api/knowledge/search?${params.toString()}`, { signal });
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: false,
  });
  const knowledgeRagHealthQuery = useQuery({
    queryKey: queryKeys.knowledgeRagHealth(activeKnowledgeActorAgentId),
    queryFn: ({ signal }) => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeRagHealthPayload>(`/api/knowledge/rag/health?${params.toString()}`, { signal });
    },
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
    queryFn: ({ signal }) => {
      const params = new URLSearchParams();
      params.set("agentId", activeKnowledgeActorAgentId);
      if (activeKnowledgeBaseForItems) {
        params.set("knowledgeBaseId", activeKnowledgeBaseForItems);
      }
      if (knowledgeSearchDraft.query.trim()) {
        params.set("query", knowledgeSearchDraft.query.trim());
      }
      commaList(knowledgeSearchDraft.tags).forEach((tag) => params.append("tags", tag));
      params.set("retrievalMode", knowledgeSearchDraft.searchMode);
      params.set("provider", "local");
      params.set("topK", String(knowledgeSearchDraft.ragTopK));
      params.set("maxContextChars", String(knowledgeSearchDraft.ragMaxContextChars));
      return fetchJson<KnowledgeRagRetrievalPayload>(`/api/knowledge/rag/retrieve?${params.toString()}`, { signal });
    },
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
    queryFn: ({ signal }) => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      if (ratingSuggestionStatus !== "all") {
        params.set("status", ratingSuggestionStatus);
      }
      return fetchJson<KnowledgeRatingSuggestionsPayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/rating-suggestions?${params.toString()}`,
        { signal },
      );
    },
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeBaseForItems) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const permissionAuditQuery = useQuery({
    queryKey: queryKeys.knowledgePermissionAudit(activeKnowledgeActorAgentId),
    queryFn: ({ signal }) =>
      fetchJson<KnowledgePermissionAuditPayload>(
        `/api/knowledge/permissions/audit?agentId=${encodeURIComponent(activeKnowledgeActorAgentId)}`,
        { signal },
      ),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 60_000),
    refetchIntervalInBackground: false,
  });
  const governanceTasksQuery = useQuery({
    queryKey: queryKeys.knowledgeGovernanceTasks(activeKnowledgeActorAgentId, "open"),
    queryFn: ({ signal }) =>
      fetchJson<KnowledgeGovernanceTasksPayload>(
        `/api/knowledge/governance/tasks?agentId=${encodeURIComponent(activeKnowledgeActorAgentId)}&status=open`,
        { signal },
      ),
    enabled: forcedView === "knowledge" && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const ingestionAdaptersQuery = useQuery({
    queryKey: queryKeys.knowledgeIngestionAdapters(),
    queryFn: ({ signal }) => fetchJson<KnowledgeIngestionAdaptersPayload>("/api/knowledge/ingestion-adapters", { signal }),
    enabled: forcedView === "knowledge",
    refetchInterval: false,
  });
  const knowledgeTraceQuery = useQuery({
    queryKey: queryKeys.knowledgeTrace(activeKnowledgeBaseForItems, activeKnowledgeActorAgentId, traceTargetId),
    queryFn: ({ signal }) => {
      const params = appendAgentParam(new URLSearchParams(), activeKnowledgeActorAgentId);
      return fetchJson<KnowledgeTracePayload>(
        `/api/knowledge-bases/${encodeURIComponent(activeKnowledgeBaseForItems)}/trace/${encodeURIComponent(traceTargetId)}?${params.toString()}`,
        { signal },
      );
    },
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
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        ownerType: sourceOwnerType,
        ownerId: activeSourceOwnerId,
        agentId: activeKnowledgeActorAgentId,
      });
      if (activeSourceInboxStatus) {
        params.set("status", activeSourceInboxStatus);
      }
      return fetchJson<KnowledgeSourceInboxPayload>(`/api/knowledge/sources/inbox?${params.toString()}`, { signal });
    },
    enabled: forcedView === "knowledge" && Boolean(activeSourceOwnerId) && Boolean(activeKnowledgeActorAgentId),
    refetchInterval: resolvePollingInterval(pageVisible, 45_000),
    refetchIntervalInBackground: false,
  });
  const centralSourcesQuery = useQuery({
    queryKey: queryKeys.knowledgeCentralSources(activeKnowledgeActorAgentId, sourceOwnerType, activeSourceOwnerId),
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        agentId: activeKnowledgeActorAgentId,
        ownerType: sourceOwnerType,
        ownerId: activeSourceOwnerId,
      });
      return fetchJson<KnowledgeCentralSourceRegistryPayload>(
        `/api/knowledge/sources/registry?${params.toString()}`,
        { signal },
      );
    },
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
