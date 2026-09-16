import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { querySessions } from "../api/chat";
import { filterOutTombstonedSessions } from "./sessionDeleteTombstone";

export const SESSION_SEARCH_PAGE_SIZE = 50;
const SESSION_SEARCH_DEBOUNCE_MS = 220;

export type SessionSearchFilters = {
  agentId: string;
  teamId: string;
};

/**
 * Debounced, server-paginated session search for the「全部会话」search surface.
 * Scope note: the backend `q` matches title, taskSummary (last-message
 * preview), session id and agent identity fields — it never scans transcripts.
 */
export function useSessionSearchQuery({
  queryText,
  filters,
  enabled,
}: {
  queryText: string;
  filters: SessionSearchFilters;
  enabled: boolean;
}) {
  const [debouncedQueryText, setDebouncedQueryText] = useState(queryText);
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQueryText(queryText), SESSION_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [queryText]);

  const normalizedQueryText = debouncedQueryText.trim();
  const agentId = filters.agentId.trim();
  const teamId = filters.teamId.trim();

  const query = useInfiniteQuery({
    queryKey: ["sessions", "search", normalizedQueryText, agentId, teamId, SESSION_SEARCH_PAGE_SIZE],
    initialPageParam: "",
    enabled,
    staleTime: 5_000,
    queryFn: ({ pageParam }) =>
      querySessions({
        limit: SESSION_SEARCH_PAGE_SIZE,
        cursor: String(pageParam || ""),
        q: normalizedQueryText,
        agentId,
        teamId,
      }),
    getNextPageParam: (lastPage) => lastPage.nextCursor || undefined,
  });

  const sessions = useMemo(
    () => (
      query.data
        ? filterOutTombstonedSessions(query.data.pages.flatMap((page) => page.items ?? []))
        : undefined
    ),
    [query.data],
  );
  const lastPage = query.data?.pages.at(-1);
  const totalEstimate = typeof lastPage?.totalEstimate === "number" ? lastPage.totalEstimate : undefined;

  return {
    ...query,
    sessions: sessions ?? [],
    totalEstimate,
    hasMore: Boolean(query.hasNextPage),
    loadMore: query.fetchNextPage,
    isLoadingMore: query.isFetchingNextPage,
    debouncedQueryText: normalizedQueryText,
  };
}
