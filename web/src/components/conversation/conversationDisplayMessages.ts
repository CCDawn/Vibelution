import type { ConversationMessage } from "../../api/types";
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
  const previousThought = String(previous.thought ?? "").trim();
  const nextThought = String(next.thought ?? "").trim();
  const thought = [previousThought, nextThought]
    .filter(Boolean)
    .filter((value, index, values) => values.indexOf(value) === index)
    .join("\n\n");
  return {
    ...previous,
    thought: thought || undefined,
    mentalSnapshot: next.mentalSnapshot,
    toolCalls: mergeUniqueJsonItems(previous.toolCalls, next.toolCalls),
    feedbackEvents: mergeUniqueJsonItems(previous.feedbackEvents, next.feedbackEvents),
    metadata: {
      ...(next.metadata ?? {}),
      ...(previous.metadata ?? {}),
    },
  };
}

export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const projected: ConversationMessage[] = [];
  for (const message of chronologicalConversationMessages(messages)) {
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
