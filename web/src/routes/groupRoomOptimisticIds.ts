/**
 * Client-only group-room identity + catalog projection used for optimistic
 * create (same skeleton as sessionOptimisticIds). The server never mints these
 * ids: create seeds a temp room shell and a conversation-catalog row
 * immediately, rebases to the real roomId on success, and rolls the shell back
 * on failure.
 */
import type { InfiniteData, QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";
import type { ConversationQueryResponse, ConversationSummary } from "../api/types";

const TEMP_ROOM_PREFIX = "temp-room-";

export function createTempRoomId(): string {
  const randomUuid = globalThis.crypto?.randomUUID?.();
  if (randomUuid) {
    return `${TEMP_ROOM_PREFIX}${randomUuid}`;
  }
  return `${TEMP_ROOM_PREFIX}${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function isTempRoomId(roomId: string | null | undefined): boolean {
  return String(roomId || "").trim().startsWith(TEMP_ROOM_PREFIX);
}

type ConversationsCatalogData = InfiniteData<ConversationQueryResponse, string>;

/**
 * Prepend the optimistic room row into the paginated group-room catalog so the
 * rail paints it before POST returns; the next server page reconciles the id.
 */
export function insertTempGroupRoomConversation(
  queryClient: QueryClient,
  summary: ConversationSummary,
): void {
  const conversationId = String(summary.conversationId || "").trim();
  if (!conversationId) {
    return;
  }
  queryClient.setQueriesData<ConversationsCatalogData>(
    { queryKey: queryKeys.conversationsCatalogQuery() },
    (existing) => {
      if (!existing) {
        return existing;
      }
      const alreadyListed = existing.pages.some((page) =>
        page.items.some((item) => String(item.conversationId || "").trim() === conversationId),
      );
      if (alreadyListed) {
        return existing;
      }
      const [firstPage, ...restPages] = existing.pages;
      if (!firstPage) {
        return existing;
      }
      return {
        ...existing,
        pages: [
          {
            ...firstPage,
            items: [summary, ...firstPage.items],
            totalEstimate: typeof firstPage.totalEstimate === "number"
              ? firstPage.totalEstimate + 1
              : firstPage.totalEstimate,
          },
          ...restPages,
        ],
      };
    },
  );
}

/** Strip every optimistic room row (create failure or temp→real rebase). */
export function removeTempGroupRoomConversations(queryClient: QueryClient): void {
  queryClient.setQueriesData<ConversationsCatalogData>(
    { queryKey: queryKeys.conversationsCatalogQuery() },
    (existing) => {
      if (!existing) {
        return existing;
      }
      let removed = 0;
      const pages = existing.pages.map((page) => {
        const nextItems = page.items.filter((item) => !isTempRoomId(item.conversationId));
        removed += page.items.length - nextItems.length;
        return nextItems.length === page.items.length ? page : { ...page, items: nextItems };
      });
      return removed ? { ...existing, pages } : existing;
    },
  );
}
