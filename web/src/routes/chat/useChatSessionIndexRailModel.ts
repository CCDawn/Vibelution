import { useMemo } from "react";

import type { ConversationIndexGroup } from "../conversationIndexModel";
import {
  buildGroupedGroupConversations,
  buildSessionIndexProgressPresentation,
  countGroupedGroupConversations,
  type SessionIndexProgressQuerySlice,
} from "./chatSessionIndexRailPresentation";

export type { SessionIndexProgressQuerySlice } from "./chatSessionIndexRailPresentation";
export { toSessionIndexProgressQuerySlice } from "./chatSessionIndexRailPresentation";

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
    () => buildGroupedGroupConversations(groupedConversations),
    [groupedConversations],
  );

  const groupedGroupConversationCount = useMemo(
    () => countGroupedGroupConversations(groupedGroupConversations),
    [groupedGroupConversations],
  );

  const progress = buildSessionIndexProgressPresentation(rawSessionsQuery, lang, numberFormatter);

  return {
    groupedGroupConversations,
    groupedGroupConversationCount,
    ...progress,
  };
}
