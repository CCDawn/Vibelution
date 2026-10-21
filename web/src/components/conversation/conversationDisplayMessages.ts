import type { ConversationMessage } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  isSessionTurnItemV2,
  projectConversationMessageFromTurnItemsV2,
} from "../../routes/chatTurnProtocol";
import {
  isHotRestartResumeMessage,
  isRecoverySupersededPartial,
  isRuntimeNoticeMessage,
} from "./conversationMessagePredicates";
import { chronologicalConversationMessages, messageSequenceOrder } from "./conversationMessageOrder";

type AssistantConversationMessage = Extract<ConversationMessage, { role: "assistant" }>;

function isAssistantMessage(message: ConversationMessage): message is AssistantConversationMessage {
  return message.role === "assistant";
}

function displayTurnId(message: ConversationMessage) {
  const metadataTurnId = message.metadata?.turnId;
  if (typeof metadataTurnId === "string" && metadataTurnId.trim()) {
    return metadataTurnId.trim();
  }
  return isAssistantMessage(message) ? String(message.turnId ?? "").trim() : "";
}

function sequenceOrder(message: ConversationMessage) {
  const order = messageSequenceOrder(message);
  return Number.isFinite(order) ? order : Number.POSITIVE_INFINITY;
}

/**
 * One turn can persist as several assistant rows (durable segments, a resumed
 * segment, a re-journaled tail). Those rows carry disjoint V2 items from the
 * same turn, so painting them one by one repeats the whole turn. Fold them on
 * the item identity the protocol already defines — never on text, and never by
 * discarding a row.
 */
function foldSameTurnAssistantMessages(messages: ConversationMessage[]): ConversationMessage[] {
  const byTurn = new Map<string, AssistantConversationMessage[]>();
  for (const message of messages) {
    if (!isAssistantMessage(message)) {
      continue;
    }
    const turnId = displayTurnId(message);
    if (!turnId) {
      continue;
    }
    const bucket = byTurn.get(turnId);
    if (bucket) {
      bucket.push(message);
    } else {
      byTurn.set(turnId, [message]);
    }
  }

  const foldedByTurn = new Map<string, AssistantConversationMessage>();
  for (const [turnId, bucket] of byTurn) {
    if (bucket.length < 2) {
      continue;
    }
    // Legacy rows without canonical V2 items carry no identity to fold on.
    // Leave them untouched instead of degrading them into one lossy row.
    const foldable = bucket.every((message) => (
      Array.isArray(message.turnItems)
      && message.turnItems.length > 0
      && message.turnItems.every(isSessionTurnItemV2)
    ));
    if (!foldable) {
      continue;
    }
    const ordered = [...bucket].sort((left, right) => {
      const leftOrder = sequenceOrder(left);
      const rightOrder = sequenceOrder(right);
      if (leftOrder === rightOrder) {
        return 0;
      }
      return leftOrder < rightOrder ? -1 : 1;
    });
    foldedByTurn.set(turnId, {
      ...ordered[0],
      turnItems: consolidateSessionTurnItemsV2(...ordered.map((message) => message.turnItems)),
    });
  }

  if (foldedByTurn.size === 0) {
    return messages;
  }

  const emitted = new Set<string>();
  const result: ConversationMessage[] = [];
  for (const message of messages) {
    if (!isAssistantMessage(message)) {
      result.push(message);
      continue;
    }
    const turnId = displayTurnId(message);
    const folded = turnId ? foldedByTurn.get(turnId) : undefined;
    if (!folded) {
      result.push(message);
      continue;
    }
    if (emitted.has(turnId)) {
      continue;
    }
    emitted.add(turnId);
    result.push(folded);
  }
  return result;
}

export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const canonicalMessages = messages.map(projectConversationMessageFromTurnItemsV2);
  // Error de-duplication is item identity/revision based.  Never merge a
  // second synthetic message shape just to hide repeated status text.
  return foldSameTurnAssistantMessages(chronologicalConversationMessages(canonicalMessages))
    .filter((message) => !isRuntimeNoticeMessage(message))
    // Superseded interrupted partials stay in the journal; they only leave the
    // display timeline once a recovery turn replaces them.
    .filter((message) => !isRecoverySupersededPartial(message))
    // The resume resubmit re-journals the user text as a system-authored row
    // (kind=hot_restart_resume); it must not duplicate the original user row.
    .filter((message) => !isHotRestartResumeMessage(message));
}
