import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import {
  assistantFinalAnswerText,
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
  hasCommittedAssistantProtocolAnswer,
  hasTerminalCanonicalTurnOutcome,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import { buildAgentMessageTimelineRowIdentities, type AgentMessageTimelineRowIdentity } from "./agentMessageTimelineRows";
import { chronologicalConversationMessages } from "./conversationMessageOrder";
import { projectTimelineProcessMessages } from "./timelineMessageProcessProjection";

export type AgentMessageTimelineProjectionInput = {
  timelineMessages: ConversationMessage[];
  activeTurnMessage?: ConversationMessage;
  companionMode?: boolean;
};

export type AgentMessageTimelineProjection = {
  messages: ConversationMessage[];
  agentMessages: AgentMessage[];
  streamingMessages: ConversationMessage[];
  rowIdentities: AgentMessageTimelineRowIdentity[];
};

function hasVisibleTurnData(message: ConversationMessage) {
  if (message.role === "user") {
    return Boolean(String(message.content ?? "").trim() || message.attachments?.length || message.references?.length);
  }
  // Keep in-flight rows with empty turnItems (optimistic pending|running waiting shell).
  return message.turnItems.length > 0 || assistantTurnIsInFlight(message);
}

/**
 * Live SSE snapshots can be observed between an item shell and its first text
 * revision. Keep that incomplete transport shape out of the strict renderer
 * adapter without changing its canonical identity, status or ordering.
 */
function normalizeTurnItemForRenderer(item: SessionTurnItem): SessionTurnItem {
  switch (item.type) {
    case "agent_message":
    case "reasoning":
    case "status":
    case "error":
      return typeof item.text === "string" ? item : { ...item, text: String(item.text ?? "") };
    case "retry":
      return typeof item.reason === "string" ? item : { ...item, reason: String(item.reason ?? "") };
    case "tool_call":
      return typeof item.toolName === "string" ? item : { ...item, toolName: String(item.toolName ?? "") };
  }
}

function normalizeConversationMessageForRenderer(message: ConversationMessage): ConversationMessage {
  if (message.role === "user") {
    const content = typeof message.content === "string" ? message.content : String(message.content ?? "");
    return content === message.content ? message : { ...message, content };
  }

  const sourceItems = Array.isArray(message.turnItems) ? message.turnItems : [];
  const turnItems = sourceItems.map(normalizeTurnItemForRenderer);
  const itemsChanged = sourceItems !== message.turnItems || turnItems.some((item, index) => item !== sourceItems[index]);
  return itemsChanged ? { ...message, turnItems } : message;
}

function messageTimestampEpoch(message: ConversationMessage) {
  const parsed = Date.parse(message.timestamp);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function messageTurnId(message: ConversationMessage) {
  return String(
    (message.role === "assistant" ? message.turnId : undefined)
    ?? message.metadata?.turnId
    ?? message.metadata?.turn_id
    ?? "",
  ).replace(/^live:/, "").trim();
}

function suppressSupersededCompanionInFlightMessages(messages: ConversationMessage[]) {
  const terminalAssistants = messages.flatMap((message) => {
    if (
      message.role !== "assistant"
      || (!hasTerminalCanonicalTurnOutcome(message) && !hasCommittedAssistantProtocolAnswer(message))
    ) {
      return [];
    }
    const timestamp = messageTimestampEpoch(message);
    return timestamp === undefined ? [] : [{ message, timestamp }];
  });
  if (terminalAssistants.length === 0) {
    return messages;
  }
  return messages.filter((message) => {
    if (
      message.role !== "assistant"
      || !assistantTurnIsInFlight(message)
      || assistantFinalAnswerText(message).trim()
    ) {
      return true;
    }
    const timestamp = messageTimestampEpoch(message);
    if (timestamp === undefined) {
      return true;
    }
    const turnId = messageTurnId(message);
    return !terminalAssistants.some((terminal) => (
      terminal.timestamp > timestamp
      && messageTurnId(terminal.message) !== turnId
    ));
  });
}

/**
 * Convert the canonical session stream to the renderer model exactly once.
 * There is no side-channel merge of thought, feedback, transcript or content.
 */
export function projectAgentMessageTimelineMessages({
  timelineMessages,
  activeTurnMessage,
  companionMode = false,
}: AgentMessageTimelineProjectionInput): AgentMessageTimelineProjection {
  const canonicalTimeline = timelineMessages
    .map(projectConversationMessageFromTurnItemsV2)
    .map(normalizeConversationMessageForRenderer);
  const canonicalActiveTurn = activeTurnMessage
    ? normalizeConversationMessageForRenderer(projectConversationMessageFromTurnItemsV2(activeTurnMessage))
    : undefined;
  const folded = projectTimelineProcessMessages([
    ...canonicalTimeline,
    ...(canonicalActiveTurn ? [canonicalActiveTurn] : []),
  ]);
  const orderedMessages = chronologicalConversationMessages(folded).filter(hasVisibleTurnData);
  const messages = companionMode
    ? suppressSupersededCompanionInFlightMessages(orderedMessages)
    : orderedMessages;
  const agentMessages = messages.map(conversationMessageToAgentMessage);
  return {
    messages,
    agentMessages,
    streamingMessages: messages.filter(assistantTurnIsStreaming),
    rowIdentities: buildAgentMessageTimelineRowIdentities(agentMessages),
  };
}
