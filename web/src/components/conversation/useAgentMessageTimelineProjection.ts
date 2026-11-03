import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread/types";
import {
  assistantFinalAnswerText,
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
  consolidateSessionTurnItemsV2,
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
import { projectGuidanceWorkSegments } from "./conversationGuidanceSegments";
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
  /**
   * Overlay rows (live/active) that this projection retired together with the
   * row id that replaced them. The conversation expansion store consumes these
   * to carry explicit user expand toggles across the live→durable identity
   * change instead of resetting the sections to their collapsed defaults.
   */
  retiredOverlayAliases: readonly RetiredOverlayAlias[];
};

/** A retired overlay row id and the row id that now paints the same turn. */
export type RetiredOverlayAlias = {
  fromMessageId: string;
  toMessageId: string;
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
 * until the turn settles. Keep the chosen row identity, but merge its items
 * with the other overlays before folding durable segments.
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

/**
 * Mirrors the durable-segment fold winner in `mergeSameAssistantTurn`: the
 * chronologically last highest-status segment keeps its row id after the fold,
 * so an overlay retiring on settle must alias to exactly that id.
 */
function durableSegmentStatusRank(
  message: Extract<ConversationMessage, { role: "assistant" }>,
): number {
  switch (message.status) {
    case "failed":
      return 3;
    case "completed":
      return 2;
    case "running":
      return 1;
    default:
      return 0;
  }
}

function dedupeAssistantTurnOverlays(
  messages: ConversationMessage[],
  activeTurnMessage?: ConversationMessage,
): { messages: ConversationMessage[]; aliases: RetiredOverlayAlias[] } {
  const isOverlay = (message: ConversationMessage) => (
    message === activeTurnMessage
    || message.metadata?.kind === "session_active_turn_layer"
    || message.metadata?.kind === "session_live_overlay"
    || /-message-(live|active)-/.test(message.id)
  );
  const winnerByTurnId = new Map<string, ConversationMessage>();
  const settledTurnIds = new Set<string>();
  const overlaysByTurnId = new Map<string, Extract<ConversationMessage, { role: "assistant" }>[]>();
  const durablesByTurnId = new Map<string, Extract<ConversationMessage, { role: "assistant" }>[]>();
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
      const durables = durablesByTurnId.get(turnId) ?? [];
      durables.push(message);
      durablesByTurnId.set(turnId, durables);
      if (hasTerminalCanonicalTurnOutcome(message) || hasCommittedAssistantProtocolAnswer(message)) {
        settledTurnIds.add(turnId);
      }
      continue;
    }
    const overlays = overlaysByTurnId.get(turnId) ?? [];
    overlays.push(message);
    overlaysByTurnId.set(turnId, overlays);
    const current = winnerByTurnId.get(turnId);
    // Strictly greater keeps the first message on a tie, so an already painted
    // row never swaps identity mid-stream.
    if (!current || assistantTurnDuplicateRank(message) > assistantTurnDuplicateRank(current)) {
      winnerByTurnId.set(turnId, message);
    }
  }
  if (winnerByTurnId.size === 0) {
    return { messages, aliases: [] };
  }
  const aliases: RetiredOverlayAlias[] = [];
  const aliasIdentities = new Set<string>();
  const recordAlias = (fromMessageId: string, toMessageId: string) => {
    if (!fromMessageId || !toMessageId || fromMessageId === toMessageId) {
      return;
    }
    const identity = `${fromMessageId}\u0000${toMessageId}`;
    if (aliasIdentities.has(identity)) {
      return;
    }
    aliasIdentities.add(identity);
    aliases.push({ fromMessageId, toMessageId });
  };
  const settledDurableWinnerByTurnId = new Map<string, string>();
  const settledDurableWinnerId = (turnId: string): string => {
    const cached = settledDurableWinnerByTurnId.get(turnId);
    if (cached !== undefined) {
      return cached;
    }
    let winner: Extract<ConversationMessage, { role: "assistant" }> | undefined;
    for (const candidate of chronologicalConversationMessages(durablesByTurnId.get(turnId) ?? [])) {
      if (candidate.role !== "assistant") {
        continue;
      }
      if (!winner || durableSegmentStatusRank(candidate) >= durableSegmentStatusRank(winner)) {
        winner = candidate;
      }
    }
    const winnerId = winner?.id ?? "";
    settledDurableWinnerByTurnId.set(turnId, winnerId);
    return winnerId;
  };
  const nextMessages = messages.flatMap((message) => {
    if (message.role !== "assistant" || !isOverlay(message)) {
      return [message];
    }
    const turnId = messageTurnId(message);
    if (!turnId) {
      return [message];
    }
    if (settledTurnIds.has(turnId)) {
      // The durable turn committed and replaced this overlay; hand any
      // expansion bound to the overlay id to the surviving durable row.
      recordAlias(message.id, settledDurableWinnerId(turnId));
      return [];
    }
    if (winnerByTurnId.get(turnId) !== message) {
      // A better overlay took over the turn (rank swap): chain the state onto
      // the winner so a later settle can move it to the durable row.
      recordAlias(message.id, winnerByTurnId.get(turnId)?.id ?? "");
      return [];
    }
    const overlays = overlaysByTurnId.get(turnId) ?? [];
    return overlays.length > 1
      ? [{ ...message, turnItems: consolidateSessionTurnItemsV2(...overlays.map((overlay) => overlay.turnItems)) }]
      : [message];
  });
  return { messages: nextMessages, aliases };
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
  const deduplicated = dedupeAssistantTurnOverlays([
    ...canonicalTimeline,
    ...(canonicalActiveTurn ? [canonicalActiveTurn] : []),
  ], canonicalActiveTurn);
  const folded = projectTimelineProcessMessages(
    dedupeSettledUserSubmissions(deduplicated.messages),
  );
  const ordered = chronologicalConversationMessages(folded);
  const orderedMessages = (companionMode ? ordered : projectGuidanceWorkSegments(ordered)).filter(hasVisibleTurnData);
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
    retiredOverlayAliases: deduplicated.aliases,
  };
}
