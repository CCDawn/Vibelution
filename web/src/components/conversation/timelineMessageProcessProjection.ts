import type { ConversationMessage, SessionTurnItemStatus } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import { chronologicalConversationMessages } from "./conversationMessageOrder";

function terminalStatusRank(status: SessionTurnItemStatus) {
  if (status === "failed") return 3;
  if (status === "completed") return 2;
  if (status === "running") return 1;
  return 0;
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
  const winner = nextRank >= previousRank ? next : previous;
  return {
    ...winner,
    turnItems: consolidateSessionTurnItemsV2(previous.turnItems, next.turnItems),
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
