import type { ConversationMessage, SessionTurnItemStatus } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  hasTerminalTurnOutcomeItems,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import { chronologicalConversationMessages } from "./conversationMessageOrder";

function terminalStatusRank(status: SessionTurnItemStatus) {
  if (status === "failed") return 3;
  if (status === "completed") return 2;
  if (status === "running") return 1;
  return 0;
}

function isLiveTurnStatus(status: SessionTurnItemStatus) {
  return status === "running" || status === "pending";
}

function projectedIds(...messages: ConversationMessage[]) {
  return [...new Set(messages.flatMap((message) => {
    const ids = message.metadata?.projectedMessageIds;
    return Array.isArray(ids) ? ids.map((id) => String(id).trim()).filter(Boolean) : [message.id];
  }))];
}

function mergeSameAssistantTurn(
  previous: Extract<ConversationMessage, { role: "assistant" }>,
  next: Extract<ConversationMessage, { role: "assistant" }>,
): Extract<ConversationMessage, { role: "assistant" }> {
  const previousRank = terminalStatusRank(previous.status);
  const nextRank = terminalStatusRank(next.status);
  const turnItems = consolidateSessionTurnItemsV2(previous.turnItems, next.turnItems);
  // A mid-turn durable segment can already report `completed` while its turn
  // keeps executing and only terminal tool/reasoning items exist. Only a real
  // final-answer/failed outcome may outrank the still-running revision.
  const settled = hasTerminalTurnOutcomeItems(turnItems);
  const live = settled
    ? undefined
    : [previous, next].find((message) => isLiveTurnStatus(message.status));
  const winner = live ?? (nextRank >= previousRank ? next : previous);
  return {
    ...winner,
    turnItems,
    metadata: {
      ...(previous.metadata ?? {}),
      ...(next.metadata ?? {}),
      projectedMessageIds: projectedIds(previous, next),
    },
  };
}

/**
 * The timeline has one row per assistant turn. Stream overlays and persisted
 * snapshots are folded by `turnId`; each row keeps only revisioned turnItems.
 */
export function projectTimelineProcessMessages(messages: ConversationMessage[]) {
  const projected: ConversationMessage[] = [];
  const assistantTurnIndexes = new Map<string, number>();
  for (const message of chronologicalConversationMessages(messages.map(projectConversationMessageFromTurnItemsV2))) {
    if (message.role !== "assistant") {
      projected.push(message);
      continue;
    }
    const existingIndex = assistantTurnIndexes.get(message.turnId);
    if (existingIndex === undefined) {
      assistantTurnIndexes.set(message.turnId, projected.length);
      projected.push(message);
      continue;
    }
    const existing = projected[existingIndex];
    if (existing?.role === "assistant") {
      projected[existingIndex] = mergeSameAssistantTurn(existing, message);
    }
  }
  return projected;
}
