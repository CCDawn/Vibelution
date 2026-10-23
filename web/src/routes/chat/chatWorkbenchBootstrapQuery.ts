import { queryOptions, type InfiniteData, type QueryClient } from "@tanstack/react-query";

import { fetchChatWorkbenchBootstrap } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import type { ConversationQueryResponse, SessionQueryResponse, SessionSummary } from "../../api/types";
import { SESSION_INDEX_PAGE_SIZE } from "../chatSessionIndexQuery";
import { isSessionCreatePreserved, mergePreservedCreatedSessions } from "../sessionCreatePreserve";
import { filterOutTombstonedSessions } from "../sessionDeleteTombstone";
import { isTempSessionId } from "../sessionOptimisticIds";

/** The group-room half of the conversation index; direct rows use the session index. */
export const CONVERSATIONS_CATALOG_PAGE_SIZE = 100;
const DIRECTORY_READY_POLL_MS = 1_000;

/** Shared by shell warmup and the route so cache seeding has one owner. */
export function chatWorkbenchBootstrapQueryOptions(queryClient: QueryClient) {
  return queryOptions({
    queryKey: ["sessions", "active-bootstrap"],
    queryFn: async ({ signal }) => {
      const payload = await fetchChatWorkbenchBootstrap({ signal });
      signal.throwIfAborted();
      queryClient.setQueryData(queryKeys.agents(), payload.agents);
      // A startup empty page is not an authoritative empty directory. Leave
      // loaded pages and optimistic rows untouched until the store can answer.
      if (payload.directoryReady === false) return payload;
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
      // Bootstrap uses the server's updatedAt_desc order. Seed both equivalent
      // default keys, never a searched or differently sorted session index.
      const bootstrapSessionKeys = ["", "updatedAt_desc"].map((sort) =>
        queryKeys.sessionQuery("", SESSION_INDEX_PAGE_SIZE, "", sort),
      );
      const isOptimisticOnly = (items: SessionSummary[]) => items.length > 0 && items.every((session) =>
        isTempSessionId(session.id) || isSessionCreatePreserved(session.id),
      );
      // Bootstrap only fills a missing index (or an optimistic placeholder).
      // An index response may have arrived during this request, and loaded
      // pages/cursors belong to that query rather than this startup projection.
      const bootstrapSessionCaches = bootstrapSessionKeys.map((key) => {
        const data = queryClient.getQueryData<InfiniteData<SessionQueryResponse, string>>(key);
        return {
          key,
          items: data?.pages.flatMap((page) => page.items ?? []) ?? [],
          shouldSeed: !data || data.pages.length === 0 || (
            data.pages.length === 1 && isOptimisticOnly(data.pages[0].items ?? [])
          ),
        };
      });
      const previousItems = bootstrapSessionCaches.flatMap((cache) => cache.items);
      const currentSessions = filterOutTombstonedSessions(queryClient.getQueryData<SessionSummary[]>(queryKeys.sessions()));
      // Decide before mergePreservedCreatedSessions clears server-acknowledged pins.
      const preserveCurrentSessions = currentSessions !== undefined && !isOptimisticOnly(currentSessions);
      const mergedItems = mergePreservedCreatedSessions(payload.sessionPage?.items ?? [], {
        localItems: previousItems,
      });
      const mergedPage = {
        ...payload.sessionPage,
        items: mergedItems,
      };
      for (const { key, shouldSeed } of bootstrapSessionCaches) {
        if (shouldSeed) {
          queryClient.setQueryData(key, { pages: [mergedPage], pageParams: [""] });
        }
      }
      queryClient.setQueryData<SessionSummary[]>(queryKeys.sessions(), (existing) =>
        mergePreservedCreatedSessions(preserveCurrentSessions ? currentSessions : mergedItems, {
          localItems: existing ?? previousItems,
        }),
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
}
