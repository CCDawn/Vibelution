import { useMemo } from "react";

import type { ConversationIndexGroup } from "../conversationIndexModel";
import {
  buildGroupedGroupConversations,
  countGroupedGroupConversations,
} from "./chatSessionIndexRailPresentation";

export type UseChatSessionIndexRailModelInput = {
  groupedConversations: readonly ConversationIndexGroup[];
  /** Team ids rendered by Agent directory team blocks; their tree groups are dropped. */
  directoryTeamIds?: ReadonlySet<string>;
};

export type UseChatSessionIndexRailModelResult = {
  groupedGroupConversations: ConversationIndexGroup[];
  groupedGroupConversationCount: number;
};

export function useChatSessionIndexRailModel({
  groupedConversations,
  directoryTeamIds,
}: UseChatSessionIndexRailModelInput): UseChatSessionIndexRailModelResult {
  const groupedGroupConversations = useMemo(
    () => buildGroupedGroupConversations(groupedConversations, directoryTeamIds),
    [groupedConversations, directoryTeamIds],
  );

  const groupedGroupConversationCount = useMemo(
    () => countGroupedGroupConversations(groupedGroupConversations),
    [groupedGroupConversations],
  );

  return {
    groupedGroupConversations,
    groupedGroupConversationCount,
  };
}
