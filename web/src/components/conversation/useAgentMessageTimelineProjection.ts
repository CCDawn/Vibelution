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
import {
  companionMessageSpokenText,
  companionTurnHasVisibleError,
  companionUnrepeatedSpeech,
} from "./companionSpokenDisplay";
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

function suppressCompanionRestatedFollowups(messages: ConversationMessage[]) {
  let previousAnswer = "";
  return messages.filter((message) => {
    if (message.role === "user") {
      previousAnswer = "";
      return true;
    }
    if (message.role !== "assistant") {
      return true;
    }
    const spoken = companionMessageSpokenText(message);
    if (assistantTurnIsInFlight(message) && !spoken) {
      return true;
    }
    if (!spoken) {
      return companionTurnHasVisibleError(message);
    }
    const visible = companionUnrepeatedSpeech(previousAnswer, spoken);
    if (visible) {
      previousAnswer = spoken;
    }
    return Boolean(visible) || companionTurnHasVisibleError(message);
  });
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
 * One live turn can reach the renderer as two overlays: the backend projection
 * (`<sessionId>-message-live-<turnId>`, kind `session_live_overlay`) and the
 * frontend active turn layer (`<sessionId>-message-active-<turnId>`, kind
 * `session_active_turn_layer`). Their ids never collide and each one retires on
 * its own rule, so concatenating both paints the same in-flight answer twice
 * until the turn settles. Select one overlay, leaving all durable segments for
 * projectTimelineProcessMessages to fold by revisioned item identity.
 */
function assistantOverlayHasText(message: ConversationMessage): boolean {
  if (message.role !== "assistant") {
    return false;
  }
  if (assistantFinalAnswerText(message).trim()) {
    return true;
  }
  return (message.turnItems ?? []).some((item) => (
    (item.type === "agent_message" || item.type === "reasoning")
    && String(item.text ?? "").trim().length > 0
  ));
}

function assistantTurnDuplicateRank(message: ConversationMessage): number {
  if (hasTerminalCanonicalTurnOutcome(message) || hasCommittedAssistantProtocolAnswer(message)) {
    return 4;
  }
  // `hasVisibleTurnData` treats an empty in-flight shell as visible, which would
  // let a pending placeholder shadow an overlay that already streams text.
  const hasContent = assistantOverlayHasText(message);
  const kind = String(message.metadata?.kind ?? "").trim();
  // An empty overlay must never shadow a sibling that already streams text, and
  // a content-bearing active layer beats the coarser backend projection because
  // it repaints from the lowest-latency stream.
  if (kind === "session_active_turn_layer") {
    return hasContent ? 3 : 1;
  }
  if (kind === "session_live_overlay" || /-message-live-/.test(String(message.id ?? ""))) {
    return hasContent ? 2 : 1;
  }
  return hasContent ? 3 : 1;
}

function userSubmissionIdentity(message: ConversationMessage): string {
  if (message.role !== "user") {
    return "";
  }
  return String(message.metadata?.clientSubmissionId ?? "").trim();
}

function isOptimisticUserRow(message: ConversationMessage): boolean {
  return message.role === "user"
    && (message.metadata?.optimisticUserMessage === true || message.id.startsWith("optimistic-user-"));
}

/**
 * The optimistic user row and its canonical twin share one `clientSubmissionId`
 * identity, so they must never paint as two bubbles. Resolving the duplicate on
 * that identity keeps the single-row contract independent of the settle delete,
 * which still falls back to content and time heuristics when the projection
 * drops the metadata on the way back.
 */
export function dedupeSettledUserSubmissions(
  messages: ConversationMessage[],
): ConversationMessage[] {
  const winners = new Map<string, ConversationMessage>();
  for (const message of messages) {
    const identity = userSubmissionIdentity(message);
    if (!identity) {
      continue;
    }
    const current = winners.get(identity);
    // The committed row always wins; on an optimistic-only tie the first row
    // keeps the painted identity instead of remounting mid-stream.
    if (!current || (isOptimisticUserRow(current) && !isOptimisticUserRow(message))) {
      winners.set(identity, message);
    }
  }
  if (winners.size === 0) {
    return messages;
  }
  return messages.filter((message) => {
    const identity = userSubmissionIdentity(message);
    if (!identity) {
      return true;
    }
    return winners.get(identity) === message;
  });
}

function dedupeAssistantTurnOverlays(
  messages: ConversationMessage[],
  activeTurnMessage?: ConversationMessage,
): ConversationMessage[] {  const isOverlay = (message: ConversationMessage) => (
    message === activeTurnMessage
    || message.metadata?.kind === "session_active_turn_layer"
    || message.metadata?.kind === "session_live_overlay"
    || /-message-(live|active)-/.test(message.id)
  );
  const winnerByTurnId = new Map<string, ConversationMessage>();
  const settledTurnIds = new Set<string>();
  for (const message of messages) {
    if (message.role !== "assistant") {
      continue;
    }
    const turnId = messageTurnId(message);
    if (!turnId) {
      continue;
    }
    // Durable segments can contain different items from the same turn. Only
    // their terminal outcome competes with overlays; never discard a segment.
    if (!isOverlay(message)) {
      if (hasTerminalCanonicalTurnOutcome(message) || hasCommittedAssistantProtocolAnswer(message)) {
        settledTurnIds.add(turnId);
      }
      continue;
    }
    const current = winnerByTurnId.get(turnId);
    // Strictly greater keeps the first message on a tie, so an already painted
    // row never swaps identity mid-stream.
    if (!current || assistantTurnDuplicateRank(message) > assistantTurnDuplicateRank(current)) {
      winnerByTurnId.set(turnId, message);
    }
  }
  if (winnerByTurnId.size === 0) {
    return messages;
  }
  return messages.filter((message) => {
    if (message.role !== "assistant" || !isOverlay(message)) {
      return true;
    }
    const turnId = messageTurnId(message);
    if (!turnId) {
      return true;
    }
    return !settledTurnIds.has(turnId) && winnerByTurnId.get(turnId) === message;
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
  const folded = projectTimelineProcessMessages(
dedupeSettledUserSubmissions(dedupeAssistantTurnOverlays([
      ...canonicalTimeline,
      ...(canonicalActiveTurn ? [canonicalActiveTurn] : []),
    ], canonicalActiveTurn)),  );
  const orderedMessages = chronologicalConversationMessages(folded).filter(hasVisibleTurnData);
  const messages = companionMode
    ? suppressCompanionRestatedFollowups(
      suppressSupersededCompanionInFlightMessages(orderedMessages),
    )
    : orderedMessages;
  const agentMessages = messages.map(conversationMessageToAgentMessage);
  return {
    messages,
    agentMessages,
    streamingMessages: messages.filter(assistantTurnIsStreaming),
    rowIdentities: buildAgentMessageTimelineRowIdentities(agentMessages),
  };
}
