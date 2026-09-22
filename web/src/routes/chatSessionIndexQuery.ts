import { useInfiniteQuery, type InfiniteData, type QueryClient, type QueryKey } from "@tanstack/react-query";
import { useMemo } from "react";

import { querySessions } from "../api/chat";
import { queryKeys } from "../api/queryKeys";
import type {
  AgentInstance,
  SessionDetail,
  SessionQueryResponse,
  SessionSummary,
} from "../api/types";
import { mergeSessionDetailIntoSummaries } from "./chatSessionState";
import { mergePreservedCreatedSessions, unpinSessionCreatePreserve } from "./sessionCreatePreserve";
import { stabilizeSessionSummaries } from "./sessionIndexReferenceStabilization";
import { filterOutTombstonedSessions, markSessionDeleteTombstone } from "./sessionDeleteTombstone";
import { chatAgentSessionStorage, forgetAgentLastSessionBySessionId } from "./chat/chatAgentSessionMemory";

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
  // Reuse previous summary references for content-equivalent entries so a
  // <=350ms stream apply only rotates the session that actually changed.
  const stabilizedSessions = stabilizeSessionSummaries(previousSessions, nextSessions);
  if (stabilizedSessions === previousSessions) {
    // Identical membership, content, and order: re-slicing would reproduce
    // `data` exactly, so keep the whole cached value reference-stable.
    return data;
  }
  const sessionDelta = stabilizedSessions.length - previousSessions.length;
  let cursor = 0;
  let allPagesReused = true;
  const nextPages = data.pages.map((page, index) => {
    const isLastPage = index === data.pages.length - 1;
    const pageSize = isLastPage
      ? Math.max(page.items.length, stabilizedSessions.length - cursor)
      : page.items.length;
    const items = stabilizedSessions.slice(cursor, cursor + pageSize);
    cursor += pageSize;
    const totalEstimate =
      typeof page.totalEstimate === "number"
        ? Math.max(0, page.totalEstimate + sessionDelta)
        : page.totalEstimate;
    if (
      page.items.length === items.length
      && page.items.every((item, itemIndex) => item === items[itemIndex])
      && page.totalEstimate === totalEstimate
    ) {
      // Unchanged partition: reuse the previous page object so only the page
      // that actually contains a changed session rotates.
      return page;
    }
    allPagesReused = false;
    return {
      ...page,
      items,
      totalEstimate,
    };
  });
  if (nextPages.length === 0) {
    return data;
  }
  if (cursor < stabilizedSessions.length) {
    allPagesReused = false;
    const lastPage = nextPages[nextPages.length - 1];
    nextPages[nextPages.length - 1] = {
      ...lastPage,
      items: [...lastPage.items, ...stabilizedSessions.slice(cursor)],
    };
  }
  if (allPagesReused) {
    return data;
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
  // Stabilize against the previous cached list so a stream apply that does not
  // change summary content keeps both cache values reference-identical.
  queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (previous) => {
    const next = updater(previous);
    if (!next || !previous) {
      return next;
    }
    return stabilizeSessionSummaries(previous, next);
  });
  queryClient.setQueriesData<SessionQueryInfiniteData>({ queryKey: ["sessions", "query"] }, (data) =>
    data ? repartitionSessionPages(data, updater) : data,
  );
}

/**
 * Drop an unopenable session from list caches without cancelling the active
 * detail query, so an explicit URL can still settle on the unavailable surface.
 */
export function evictUnopenableSessionFromCaches(queryClient: QueryClient, sessionId: string) {
  const normalizedSessionId = String(sessionId || "").trim();
  if (!normalizedSessionId) {
    return;
  }
  markSessionDeleteTombstone(normalizedSessionId);
  // A 404 proves the session is gone: stale per-Agent last-viewed pointers must
  // not keep reopening it on the next Agent-directory click.
  forgetAgentLastSessionBySessionId(normalizedSessionId, chatAgentSessionStorage());
  unpinSessionCreatePreserve(normalizedSessionId);
  updateSessionSummaryCaches(queryClient, (sessions) =>
    sessions?.filter((session) => session.id !== normalizedSessionId),
  );
  removeSessionFromAgentSessionCaches(queryClient, normalizedSessionId);
}

export function updateAgentSessionSummaryCaches(queryClient: QueryClient, updater: SessionSummaryUpdater) {
  queryClient.setQueriesData<SessionQueryResponse>({ queryKey: ["sessions", "agent"] }, (data) => {
    if (!data) {
      return data;
    }
    const items = stabilizeSessionSummaries(data.items, updater(data.items) ?? data.items);
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
    // `mergeSessionDetailIntoSummaries` always spreads the target session into
    // a new object; fold that back onto the cached reference when the folded
    // detail did not change any summary field (recurring snapshot applies).
    const items = stabilizeSessionSummaries(data.items, mergeSessionDetailIntoSummaries(data.items, detail));
    const addedCount = items.length - data.items.length;
    if (items === data.items) {
      return data;
    }
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
      const payload = await querySessions({
        limit: SESSION_INDEX_PAGE_SIZE,
        cursor: String(pageParam || ""),
        q: normalizedQueryText,
      });
      const existing = queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()) ?? [];
      const previousPages = queryClient.getQueryData<SessionQueryInfiniteData>(
        queryKeys.sessionQuery(normalizedQueryText, SESSION_INDEX_PAGE_SIZE),
      );
      const previousPageItems = previousPages ? mergeSessionPages(previousPages.pages) : [];
      // Drop tombstoned rows, then re-attach optimistic / just-created tabs that a
      // racing bootstrap or index refetch can briefly omit after create.
      const filteredItems = stabilizeSessionSummaries(
        previousPageItems,
        mergePreservedCreatedSessions(filterOutTombstonedSessions(payload.items) ?? [], {
          localItems: previousPageItems,
        }),
      );
      const merged = stabilizeSessionSummaries(
        existing,
        filterOutTombstonedSessions(
          mergePreservedCreatedSessions(mergeSessions([existing, filteredItems]), {
            localItems: previousPageItems,
          }),
        ) ?? [],
      );
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), merged);
      return {
        ...payload,
        items: filteredItems,
      };
    },
    getNextPageParam: (lastPage) => lastPage.nextCursor || undefined,
    staleTime: 5_000,
    refetchInterval,
    refetchIntervalInBackground,
  });

  const sessions = useMemo(
    () => (query.data ? filterOutTombstonedSessions(mergeSessionPages(query.data.pages)) : undefined),
    [query.data],
  );
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
