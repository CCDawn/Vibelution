import { useMemo } from "react";
import type { Virtualizer } from "@tanstack/react-virtual";

import type { ConversationMessage } from "../../api/types";
import type { Language } from "../../i18n/dictionaryTypes";
import type { AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import {
  buildConversationTurnNavDirectory,
  resolveConversationTurnNavCurrentIndex,
  turnNavPlainPreviewText,
  turnNavPreviewText,
  type ConversationTurnNavEntry,
} from "./conversationTurnNavigation";

export type UseConversationTurnNavInput = {
  lang: Language;
  activeTimelineMessages: ConversationMessage[];
  activeTimelineRowIdentities: AgentMessageTimelineRowIdentity[];
  /** Virtualized history row count; the live tail starts at this index. */
  historyRowCount: number;
  timelineVirtualizer: Virtualizer<HTMLDivElement, Element>;
};

export type UseConversationTurnNavResult = {
  timelineTurnNavEntries: ConversationTurnNavEntry[];
  timelineTurnNavCurrentIndex: number;
};

/**
 * Turn-navigator directory and live current-turn index, extracted from
 * ConversationView. The markdown-free preview map and directory stay
 * memoized; the current index is resolved every render from the virtualizer
 * snapshot, the same way the shell rebuilds its row plan.
 */
export function useConversationTurnNav({
  lang,
  activeTimelineMessages,
  activeTimelineRowIdentities,
  historyRowCount,
  timelineVirtualizer,
}: UseConversationTurnNavInput): UseConversationTurnNavResult {
  // Turn navigation directory (minimap rail): one entry per conversation
  // turn, derived from the same row identities the virtualizer keys on. The
  // markdown-free preview map feeds the rail's VHoverCard content through the
  // entries' userPreviewText / assistantPreviewText fields.
  const timelineTurnNavPreviewTextByRowKey = useMemo(() => {
    const previewTextByRowKey = new Map<string, string>();
    activeTimelineRowIdentities.forEach((identity, index) => {
      const previewText = turnNavPlainPreviewText(activeTimelineMessages[index]);
      if (previewText) {
        previewTextByRowKey.set(identity.rowKey, previewText);
      }
    });
    return previewTextByRowKey;
  }, [activeTimelineRowIdentities, activeTimelineMessages]);
  const timelineTurnNavEntries = useMemo(
    () => buildConversationTurnNavDirectory(
      activeTimelineRowIdentities.map((identity, index) => ({
        rowKey: identity.rowKey,
        previewText: turnNavPreviewText(activeTimelineMessages[index]),
      })),
      {
        fallbackLabel: lang === "zh"
          ? (turnNumber: number) => `第 ${turnNumber} 轮`
          : (turnNumber: number) => `Turn ${turnNumber}`,
        previewTextByRowKey: timelineTurnNavPreviewTextByRowKey,
      },
    ),
    [activeTimelineRowIdentities, activeTimelineMessages, lang, timelineTurnNavPreviewTextByRowKey],
  );
  // Minimap current-turn highlight: rebuilt every render like the row plan so
  // scroll notifications stay live (virtual history + static live tail).
  const timelineTurnNavCurrentIndex = resolveConversationTurnNavCurrentIndex({
    entries: timelineTurnNavEntries,
    historyRowCount,
    historyTotalSize: timelineVirtualizer.getTotalSize(),
    scrollOffset: timelineVirtualizer.scrollOffset ?? 0,
    viewportHeight: timelineVirtualizer.scrollRect?.height ?? 0,
    rowIndexAtOffset: (offset) => {
      const item = timelineVirtualizer.getVirtualItemForOffset(offset);
      return item ? item.index : null;
    },
  });

  return {
    timelineTurnNavEntries,
    timelineTurnNavCurrentIndex,
  };
}
