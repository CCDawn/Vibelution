import { useMemo } from "react";

import type { ConversationIndexGroup } from "../conversationIndexModel";
import { SESSION_INDEX_PAGE_SIZE } from "../chatSessionIndexQuery";

export type SessionIndexProgressQuerySlice = {
  loadedCount: number;
  totalEstimate: number;
  hasMore: boolean;
  isLoadingMore: boolean;
};

export type UseChatSessionIndexRailModelInput = {
  groupedConversations: readonly ConversationIndexGroup[];
  rawSessionsQuery: SessionIndexProgressQuerySlice;
  lang: "zh" | "en";
  numberFormatter: Intl.NumberFormat;
};

export type UseChatSessionIndexRailModelResult = {
  groupedGroupConversations: ConversationIndexGroup[];
  groupedGroupConversationCount: number;
  sessionIndexLoadedCount: number;
  sessionIndexTotalEstimate: number;
  sessionIndexHasMore: boolean;
  sessionIndexLoadMoreLabel: string;
  sessionIndexFullyLoadedLabel: string;
  sessionIndexProgressLabel: string;
  sessionIndexProgressVisible: boolean;
};

export function useChatSessionIndexRailModel({
  groupedConversations,
  rawSessionsQuery,
  lang,
  numberFormatter,
}: UseChatSessionIndexRailModelInput): UseChatSessionIndexRailModelResult {
  const groupedGroupConversations = useMemo(
    () => groupedConversations
      .map((group) => ({ ...group, items: group.items.filter((conversation) => conversation.type === "group_room") }))
      .filter((group) => group.items.length > 0),
    [groupedConversations],
  );

  const groupedGroupConversationCount = useMemo(
    () => groupedGroupConversations.reduce((count, group) => count + group.items.length, 0),
    [groupedGroupConversations],
  );

  const sessionIndexLoadedCount = rawSessionsQuery.loadedCount;
  const sessionIndexTotalEstimate = rawSessionsQuery.totalEstimate;
  const sessionIndexHasMore = rawSessionsQuery.hasMore;
  const sessionIndexLoadMoreLabel = rawSessionsQuery.isLoadingMore
    ? (lang === "zh" ? "加载中" : "Loading")
    : (lang === "zh" ? "加载更多会话" : "Load more chats");
  const sessionIndexFullyLoadedLabel = lang === "zh" ? "已加载全部会话" : "All chats loaded";
  const sessionIndexProgressLabel =
    sessionIndexTotalEstimate > sessionIndexLoadedCount
      ? `${numberFormatter.format(sessionIndexLoadedCount)} / ${numberFormatter.format(sessionIndexTotalEstimate)}`
      : numberFormatter.format(sessionIndexLoadedCount);
  const sessionIndexProgressVisible = sessionIndexHasMore || sessionIndexTotalEstimate > SESSION_INDEX_PAGE_SIZE;

  return {
    groupedGroupConversations,
    groupedGroupConversationCount,
    sessionIndexLoadedCount,
    sessionIndexTotalEstimate,
    sessionIndexHasMore,
    sessionIndexLoadMoreLabel,
    sessionIndexFullyLoadedLabel,
    sessionIndexProgressLabel,
    sessionIndexProgressVisible,
  };
}
