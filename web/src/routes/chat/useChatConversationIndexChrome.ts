import {
  useCallback,
  useEffect,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  defaultConversationGroupCollapsed,
  type ConversationIndexDynamicGroupKey,
} from "../conversationIndexModel";

export type RightIndexPanel = "conversations" | "members";

export type UseChatConversationIndexChromeOptions = {
  standardGroupRoomActive: boolean;
};

export type UseChatConversationIndexChromeResult = {
  collapsedConversationGroups: Record<string, boolean>;
  rightIndexPanel: RightIndexPanel;
  setRightIndexPanel: Dispatch<SetStateAction<RightIndexPanel>>;
  toggleConversationGroup: (groupKey: ConversationIndexDynamicGroupKey) => void;
};

/**
 * Conversation-index chrome: collapsed groups and members/conversations tab.
 * Session filter stays in the shell because composer/lifecycle still share it.
 */
export function useChatConversationIndexChrome({
  standardGroupRoomActive,
}: UseChatConversationIndexChromeOptions): UseChatConversationIndexChromeResult {
  const [collapsedConversationGroups, setCollapsedConversationGroups] = useState<Record<string, boolean>>(
    DEFAULT_COLLAPSED_CONVERSATION_GROUPS,
  );
  const [rightIndexPanel, setRightIndexPanel] = useState<RightIndexPanel>("conversations");

  useEffect(() => {
    if (!standardGroupRoomActive && rightIndexPanel === "members") {
      setRightIndexPanel("conversations");
    }
  }, [standardGroupRoomActive, rightIndexPanel]);

  const toggleConversationGroup = useCallback((groupKey: ConversationIndexDynamicGroupKey) => {
    setCollapsedConversationGroups((current) => ({
      ...current,
      [groupKey]: !(current[groupKey] ?? defaultConversationGroupCollapsed(groupKey)),
    }));
  }, []);

  return {
    collapsedConversationGroups,
    rightIndexPanel,
    setRightIndexPanel,
    toggleConversationGroup,
  };
}
