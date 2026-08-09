import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import {
  assistantTurnIsStreaming,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import { buildAgentMessageTimelineRowIdentities, type AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import { chronologicalConversationMessages } from "./conversationMessageOrder";
import { projectTimelineProcessMessages } from "./timelineMessageProcessProjection";

export type AgentMessageTimelineProjectionInput = {
  timelineMessages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
};

export type AgentMessageTimelineProjection = {
  messages: ConversationMessage[];
  agentMessages: AgentMessage[];
  streamingMessages: ConversationMessage[];
  rowIdentities: AgentMessageTimelineRowIdentity[];
};

function hasVisibleTurnData(message: ConversationMessage) {
  if (message.role === "user") {
    return Boolean(message.content.trim() || message.attachments?.length || message.references?.length);
  }
  return message.turnItems.length > 0 || assistantTurnIsStreaming(message);
}

/**
 * Convert the canonical session stream to the renderer model exactly once.
 * There is no side-channel merge of thought, feedback, transcript or content.
 */
export function projectAgentMessageTimelineMessages({
  timelineMessages,
  activeTurnMessage,
}: AgentMessageTimelineProjectionInput): AgentMessageTimelineProjection {
  const canonicalTimeline = timelineMessages.map(projectConversationMessageFromTurnItemsV2);
  const canonicalActiveTurn = activeTurnMessage
    ? projectConversationMessageFromTurnItemsV2(activeTurnMessage)
    : undefined;
  const folded = projectTimelineProcessMessages([
    ...canonicalTimeline,
    ...(canonicalActiveTurn ? [canonicalActiveTurn] : []),
  ]);
  const messages = chronologicalConversationMessages(folded).filter(hasVisibleTurnData);
  const agentMessages = messages.map(conversationMessageToAgentMessage);
  return {
    messages,
    agentMessages,
    streamingMessages: messages.filter(assistantTurnIsStreaming),
    rowIdentities: buildAgentMessageTimelineRowIdentities(agentMessages),
  };
}
