import type { ConversationIndexGroup } from "../conversationIndexModel";
import { SESSION_INDEX_PAGE_SIZE } from "../chatSessionIndexQuery";

export type SessionIndexProgressQuerySlice = {
  loadedCount: number;
  totalEstimate: number;
  hasMore: boolean;
  isLoadingMore: boolean;
};

export function toSessionIndexProgressQuerySlice(source: {
  loadedCount: number;
  totalEstimate: number;
  hasMore: boolean;
  isLoadingMore: boolean;
}): SessionIndexProgressQuerySlice {
  return {
    loadedCount: source.loadedCount,
    totalEstimate: source.totalEstimate,
    hasMore: source.hasMore,
    isLoadingMore: source.isLoadingMore,
  };
}

/**
 * Tree-side group rooms. Team groups owned by the Agent directory team blocks
 * are excluded: the directory owns the linked room plus the folded history, so
 * rendering the same team here only duplicated team identity. Team groups for
 * teams without a directory block stay visible so their rooms remain reachable.
 */
export function buildGroupedGroupConversations(
  groupedConversations: readonly ConversationIndexGroup[],
  directoryTeamIds: ReadonlySet<string> = new Set<string>(),
): ConversationIndexGroup[] {
  return groupedConversations
    .filter((group) => {
      if (group.groupKind !== "team") return true;
      const teamId = String(group.teamId || "").trim();
      return !teamId || !directoryTeamIds.has(teamId);
    })
    .map((group) => ({
      ...group,
      items: group.items.filter((conversation) => conversation.type === "group_room"),
    }))
    .filter((group) => group.items.length > 0);
}

export function countGroupedGroupConversations(groups: readonly ConversationIndexGroup[]): number {
  return groups.reduce((count, group) => count + group.items.length, 0);
}

export type SessionIndexProgressPresentation = {
  sessionIndexLoadedCount: number;
  sessionIndexTotalEstimate: number;
  sessionIndexHasMore: boolean;
  sessionIndexLoadMoreLabel: string;
  sessionIndexFullyLoadedLabel: string;
  sessionIndexProgressLabel: string;
  sessionIndexProgressVisible: boolean;
};

export function buildSessionIndexProgressPresentation(
  rawSessionsQuery: SessionIndexProgressQuerySlice,
  lang: "zh" | "en",
  numberFormatter: Intl.NumberFormat,
): SessionIndexProgressPresentation {
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
  const sessionIndexProgressVisible =
    sessionIndexHasMore || sessionIndexTotalEstimate > SESSION_INDEX_PAGE_SIZE;

  return {
    sessionIndexLoadedCount,
    sessionIndexTotalEstimate,
    sessionIndexHasMore,
    sessionIndexLoadMoreLabel,
    sessionIndexFullyLoadedLabel,
    sessionIndexProgressLabel,
    sessionIndexProgressVisible,
  };
}
