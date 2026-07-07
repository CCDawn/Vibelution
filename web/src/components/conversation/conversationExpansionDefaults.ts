import type { ConversationMessage } from "../../api/types";
import type { AgentMessageRenderState } from "./agentMessageRenderState";
import type { AgentMessageTimelineItem } from "./agentMessageTimeline";
import { buildAgentMessageReActOperationGroups, type AgentMessageOperationGroups } from "./agentMessageOperations";
import { shouldExpandReActGroupByDefault } from "./conversationReActOperationItems";
import {
  compactVisibleTimelineOperations,
  operationCollectionTone,
  shouldShowTimelineOperation,
} from "./conversationOperationState";

export type ConversationExpansionDefaults = Record<string, Record<string, boolean>>;
export type ConversationSectionExpansion = Record<string, Record<string, boolean>>;

export type PreserveConversationExpansionDefaultsInput = {
  currentDefaults: ConversationExpansionDefaults;
  sectionExpansion: ConversationSectionExpansion;
  messages: ConversationMessage[];
  renderStatesByMessageId: Map<string, AgentMessageRenderState>;
  timelineItemsByMessageId: Map<string, AgentMessageTimelineItem[]>;
  operationGroupsByMessageId: Map<string, AgentMessageOperationGroups>;
  defaultExpandedResponseIds: Set<string>;
};

export function shouldRefreshConversationExpansionDefault(
  section: string,
  currentDefault: boolean | undefined,
  nextDefault: boolean,
) {
  return (section === "process" || section === "feedback")
    && currentDefault === true
    && nextDefault === false;
}

export function preserveConversationExpansionDefaults({
  currentDefaults,
  sectionExpansion,
  messages,
  renderStatesByMessageId,
  timelineItemsByMessageId,
  operationGroupsByMessageId,
  defaultExpandedResponseIds,
}: PreserveConversationExpansionDefaultsInput) {
  let changed = false;
  const nextDefaults: ConversationExpansionDefaults = { ...currentDefaults };

  for (const message of messages) {
    const messageDefaults = nextDefaults[message.id] ?? {};
    const explicit = sectionExpansion[message.id] ?? {};
    let nextMessageDefaults = messageDefaults;
    const setDefault = (section: string, value: boolean) => {
      const currentDefault = nextMessageDefaults[section] ?? messageDefaults[section];
      if (
        explicit[section] !== undefined
        || (
          currentDefault !== undefined
          && !shouldRefreshConversationExpansionDefault(section, currentDefault, value)
        )
      ) {
        return;
      }
      if (nextMessageDefaults === messageDefaults) {
        nextMessageDefaults = { ...messageDefaults };
      }
      nextMessageDefaults[section] = value;
      changed = true;
    };

    const renderState = renderStatesByMessageId.get(message.id);
    if (renderState?.sectionState.hasResponseBlock) {
      setDefault("response", Boolean(message.streaming) || defaultExpandedResponseIds.has(message.id));
    }

    const timelineItems = timelineItemsByMessageId.get(message.id) ?? [];
    for (const item of timelineItems) {
      if (item.kind === "thought") {
        setDefault(item.id, item.defaultExpanded);
        continue;
      }
      if (item.kind === "command_group") {
        setDefault(item.id, false);
      }
    }

    const operations = operationGroupsByMessageId.get(message.id)?.timeline ?? [];
    const processTone = operationCollectionTone(operations);
    if (operations.length > 0 && operations.some(shouldShowTimelineOperation)) {
      setDefault("process", processTone === "running");
      const visibleOperations = compactVisibleTimelineOperations(operations.filter(shouldShowTimelineOperation));
      const reActGroups = buildAgentMessageReActOperationGroups(visibleOperations);
      setDefault("feedback", processTone === "running" || reActGroups.some(shouldExpandReActGroupByDefault));
    }

    if (nextMessageDefaults !== messageDefaults) {
      nextDefaults[message.id] = nextMessageDefaults;
    }
  }

  return changed ? nextDefaults : currentDefaults;
}
