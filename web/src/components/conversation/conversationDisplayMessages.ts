import type { ConversationMessage } from "../../api/types";
import { projectConversationMessageFromTurnItemsV2 } from "../../routes/chatTurnProtocol";
import {
  isRuntimeNoticeMessage,
  isTurnErrorMessage,
} from "./conversationMessagePredicates";
import { chronologicalConversationMessages } from "./conversationMessageOrder";

function normalizeNoticeText(value: string) {
  return value.replace(/\s+/g, " ").trim().toLowerCase();
}

function mergeUniqueJsonItems<T>(left: T[] | undefined, right: T[] | undefined) {
  const merged = [...(left ?? [])];
  const seen = new Set(merged.map((item) => JSON.stringify(item)));
  for (const item of right ?? []) {
    const key = JSON.stringify(item);
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    merged.push(item);
  }
  return merged.length > 0 ? merged : undefined;
}

function mergeAdjacentTurnErrorMessages(previous: ConversationMessage, next: ConversationMessage): ConversationMessage {
  return {
    ...previous,
    thought: undefined,
    mentalSnapshot: undefined,
    toolCalls: undefined,
    feedbackEvents: mergeUniqueJsonItems(previous.feedbackEvents, next.feedbackEvents),
    metadata: {
      ...(next.metadata ?? {}),
      ...(previous.metadata ?? {}),
    },
  };
}

export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const projected: ConversationMessage[] = [];
  const canonicalMessages = messages.map(projectConversationMessageFromTurnItemsV2);
  for (const message of chronologicalConversationMessages(canonicalMessages)) {
    if (isRuntimeNoticeMessage(message)) {
      continue;
    }
    const previous = projected[projected.length - 1];
    if (
      previous
      && isTurnErrorMessage(previous)
      && isTurnErrorMessage(message)
      && normalizeNoticeText(previous.content) === normalizeNoticeText(message.content)
    ) {
      projected[projected.length - 1] = mergeAdjacentTurnErrorMessages(previous, message);
      continue;
    }
    projected.push(message);
  }
  return projected;
}
