import { useInfiniteQuery, type InfiniteData, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useMemo } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type { AgentInstance, SessionDetail, SessionQueryResponse, SessionSummary } from "../api/types";
import { mergeSessionDetailIntoSummaries } from "./chatSessionState";

export const SESSION_INDEX_PAGE_SIZE = 50;

type UseSessionIndexQueryOptions = {
  queryClient: QueryClient;
  queryText: string;
  enabled: boolean;
  refetchInterval: false | number;
  refetchIntervalInBackground: boolean;
};

type SessionSummaryUpdater = (sessions: SessionSummary[] | undefined) => SessionSummary[] | undefined;
type SessionQueryInfiniteData = InfiniteData<SessionQueryResponse, string>;
export type SessionIndexCacheSnapshot = Array<[QueryKey, SessionQueryInfiniteData | undefined]>;
export type AgentSessionCacheSnapshot = Array<[QueryKey, SessionQueryResponse | undefined]>;

function sessionQueryUrl(queryText: string, cursor: string): string {
  const params = new URLSearchParams();
  params.set("limit", String(SESSION_INDEX_PAGE_SIZE));
  if (cursor) {
    params.set("cursor", cursor);
  }
  if (queryText) {
    params.set("q", queryText);
  }
  return `/api/sessions/query?${params.toString()}`;
}

function mergeSessions(groups: Array<SessionSummary[] | undefined>): SessionSummary[] {
  const merged = new Map<string, SessionSummary>();
  for (const sessions of groups) {
    for (const session of sessions ?? []) {
      merged.set(session.id, session);
    }
  }
  return [...merged.values()];
}

function mergeSessionPages(pages: SessionQueryResponse[] | undefined): SessionSummary[] {
  const merged = new Map<string, SessionSummary>();
  for (const page of pages ?? []) {
    for (const session of page.items ?? []) {
      merged.set(session.id, session);
    }
  }
  return [...merged.values()];
}

function repartitionSessionPages(
  data: SessionQueryInfiniteData,
  updater: SessionSummaryUpdater,
): SessionQueryInfiniteData {
  const previousSessions = mergeSessionPages(data.pages);
  const nextSessions = updater(previousSessions) ?? previousSessions;
  const sessionDelta = nextSessions.length - previousSessions.length;
  let cursor = 0;
  const nextPages = data.pages.map((page, index) => {
    const isLastPage = index === data.pages.length - 1;
    const pageSize = isLastPage
      ? Math.max(page.items.length, nextSessions.length - cursor)
      : page.items.length;
    const items = nextSessions.slice(cursor, cursor + pageSize);
    cursor += pageSize;
    return {
      ...page,
      items,
      totalEstimate:
        typeof page.totalEstimate === "number"
          ? Math.max(0, page.totalEstimate + sessionDelta)
          : page.totalEstimate,
    };
  });
  if (nextPages.length === 0) {
    return data;
  }
  if (cursor < nextSessions.length) {
    const lastPage = nextPages[nextPages.length - 1];
    nextPages[nextPages.length - 1] = {
      ...lastPage,
      items: [...lastPage.items, ...nextSessions.slice(cursor)],
    };
  }
  return {
    ...data,
    pages: nextPages,
  };
}

export function captureSessionIndexCacheSnapshots(queryClient: QueryClient): SessionIndexCacheSnapshot {
  return queryClient.getQueriesData<SessionQueryInfiniteData>({ queryKey: ["sessions", "query"] });
}

export function captureAgentSessionCacheSnapshots(queryClient: QueryClient): AgentSessionCacheSnapshot {
  return queryClient.getQueriesData<SessionQueryResponse>({ queryKey: ["sessions", "agent"] });
}

export function restoreSessionIndexCacheSnapshots(
  queryClient: QueryClient,
  snapshots: SessionIndexCacheSnapshot | undefined,
) {
  for (const [queryKey, data] of snapshots ?? []) {
    queryClient.setQueryData(queryKey, data);
  }
}

export function restoreAgentSessionCacheSnapshots(
  queryClient: QueryClient,
  snapshots: AgentSessionCacheSnapshot | undefined,
) {
  for (const [queryKey, data] of snapshots ?? []) {
    queryClient.setQueryData(queryKey, data);
  }
}

export function removeSessionFromAgentSessionCaches(queryClient: QueryClient, sessionId: string) {
  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) {
    return;
  }
  queryClient.setQueriesData<SessionQueryResponse>({ queryKey: ["sessions", "agent"] }, (data) => {
    if (!data) {
      return data;
    }
    const items = data.items.filter((session) => session.id !== normalizedSessionId);
    const removedCount = data.items.length - items.length;
    if (removedCount === 0) {
      return data;
    }
    return {
      ...data,
      items,
      totalEstimate:
        typeof data.totalEstimate === "number"
          ? Math.max(0, data.totalEstimate - removedCount)
          : data.totalEstimate,
    };
  });
}

export function updateSessionSummaryCaches(queryClient: QueryClient, updater: SessionSummaryUpdater) {
  queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), updater);
  queryClient.setQueriesData<SessionQueryInfiniteData>({ queryKey: ["sessions", "query"] }, (data) =>
    data ? repartitionSessionPages(data, updater) : data,
  );
}

export function updateAgentSessionSummaryCaches(queryClient: QueryClient, updater: SessionSummaryUpdater) {
  queryClient.setQueriesData<SessionQueryResponse>({ queryKey: ["sessions", "agent"] }, (data) => {
    if (!data) {
      return data;
    }
    const items = updater(data.items) ?? data.items;
    return items === data.items ? data : {
      ...data,
      items,
      totalEstimate:
        typeof data.totalEstimate === "number"
          ? Math.max(0, data.totalEstimate + items.length - data.items.length)
          : data.totalEstimate,
    };
  });
}

/**
 * Reconcile the selected Agent's cached session list from the authoritative
 * detail stream without leaking that session into other Agents' query caches.
 */
export function reconcileAgentSessionDetailCache(queryClient: QueryClient, detail: SessionDetail) {
  const agentId = String(detail.agentId ?? "").trim();
  if (!agentId) {
    return;
  }
  const queryKey = ["sessions", "agent", agentId] as const;
  queryClient.setQueryData<SessionQueryResponse>(queryKey, (data) => {
    if (!data) {
      return data;
    }
    const items = mergeSessionDetailIntoSummaries(data.items, detail);
    const addedCount = items.length - data.items.length;
    return {
      ...data,
      items,
      totalEstimate:
        typeof data.totalEstimate === "number"
          ? Math.max(0, data.totalEstimate + addedCount)
          : data.totalEstimate,
    };
  });
}

export function renameAgentDirectoryEntries(
  agents: AgentInstance[] | undefined,
  agentId: string,
  title: string,
): AgentInstance[] | undefined {
  const normalizedAgentId = agentId.trim();
  if (!agents || !normalizedAgentId) {
    return agents;
  }
  return agents.map((agent) => agent.agentId === normalizedAgentId ? {
    ...agent,
    displayName: title,
  } : agent);
}

export function useSessionIndexQuery({
  queryClient,
  queryText,
  enabled,
  refetchInterval,
  refetchIntervalInBackground,
}: UseSessionIndexQueryOptions) {
  const normalizedQueryText = queryText.trim();
  const query = useInfiniteQuery({
    queryKey: queryKeys.sessionQuery(normalizedQueryText, SESSION_INDEX_PAGE_SIZE),
    initialPageParam: "",
    enabled,
    queryFn: async ({ pageParam }) => {
      const payload = await fetchJson<SessionQueryResponse>(sessionQueryUrl(normalizedQueryText, String(pageParam || "")));
      const existing = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? [];
      const merged = mergeSessions([existing, payload.items]);
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), merged);
      return payload;
    },
    getNextPageParam: (lastPage) => lastPage.nextCursor || undefined,
    refetchInterval,
    refetchIntervalInBackground,
  });

  const sessions = useMemo(() => (query.data ? mergeSessionPages(query.data.pages) : undefined), [query.data]);
  const lastPage = query.data?.pages.at(-1);
  const loadedCount = sessions?.length ?? 0;
  const totalEstimate = typeof lastPage?.totalEstimate === "number" ? lastPage.totalEstimate : loadedCount;

  return {
    ...query,
    data: sessions,
    totalEstimate,
    loadedCount,
    hasMore: Boolean(query.hasNextPage),
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
  };
}
