import type { CodexTranscriptProjection, ConversationMessage } from "../../api/types";
import {
  conversationMessageTurnId,
  projectedConversationMessageIdsOrSelf,
} from "./conversationMessageIdentity";
import {
  isCliAgentLifecycleMessage,
  isGroupRoomTranscriptMessage,
  isRuntimeNoticeMessage,
  isTurnErrorMessage,
} from "./conversationMessagePredicates";
import { answerProjectionContent } from "./conversationInternalStatus";

function exactItemKey(value: unknown) {
  return JSON.stringify(value) ?? String(value);
}

function mergeExactItems<T>(...itemGroups: Array<T[] | undefined>) {
  const merged: T[] = [];
  const seen = new Set<string>();
  for (const group of itemGroups) {
    for (const item of group ?? []) {
      const key = exactItemKey(item);
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      merged.push(item);
    }
  }
  return merged.length > 0 ? merged : undefined;
}

function mergeText(...values: Array<string | undefined>) {
  const merged: string[] = [];
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text) {
      continue;
    }
    if (merged.some((existing) => existing === text || existing.includes(text))) {
      continue;
    }
    for (let index = merged.length - 1; index >= 0; index -= 1) {
      if (text.includes(merged[index])) {
        merged.splice(index, 1);
      }
    }
    merged.push(text);
  }
  return merged.join("\n\n");
}

function mergeCodexTranscripts(
  previous: CodexTranscriptProjection | undefined,
  next: CodexTranscriptProjection | undefined,
  messageId: string,
): CodexTranscriptProjection | undefined {
  if (!previous) {
    return next;
  }
  if (!next) {
    return previous;
  }
  return {
    ...previous,
    ...next,
    messageId,
    streaming: Boolean(previous.streaming || next.streaming) || undefined,
    cells: mergeExactItems(previous.cells, next.cells) ?? [],
    rolloutEvents: mergeExactItems(previous.rolloutEvents, next.rolloutEvents),
    toolCalls: mergeExactItems(previous.toolCalls, next.toolCalls) ?? [],
    terminalOperations: mergeExactItems(previous.terminalOperations, next.terminalOperations) ?? [],
    terminalSessions: mergeExactItems(previous.terminalSessions, next.terminalSessions) ?? [],
    modelObservations: mergeExactItems(previous.modelObservations, next.modelObservations) ?? [],
  };
}

function isExcludedAssistantProjectionMessage(message: ConversationMessage) {
  if (
    message.role !== "assistant"
    || isRuntimeNoticeMessage(message)
    || isCliAgentLifecycleMessage(message)
    || isGroupRoomTranscriptMessage(message)
    || isTurnErrorMessage(message)
  ) {
    return true;
  }
  return false;
}

function isProjectableProcessOnlyMessage(message: ConversationMessage) {
  if (isExcludedAssistantProjectionMessage(message) || String(answerProjectionContent(message) ?? "").trim()) {
    return false;
  }
  return Boolean(
    String(message.streamStage ?? "").trim()
    || (message.feedbackEvents?.length ?? 0) > 0
    || (message.timelineItems?.length ?? 0) > 0
    || hasVisibleNativeTranscript(message)
  );
}

function hasVisibleNativeTranscript(message: ConversationMessage) {
  const transcript = message.codexTranscript;
  return Boolean(
    transcript
    && String(transcript.source ?? "").trim() === "native"
    && (
      (transcript.cells?.length ?? 0) > 0
      || (transcript.rolloutEvents?.length ?? 0) > 0
      || (transcript.toolCalls?.length ?? 0) > 0
      || (transcript.terminalOperations?.length ?? 0) > 0
      || (transcript.terminalSessions?.length ?? 0) > 0
      || (transcript.modelObservations?.length ?? 0) > 0
    )
  );
}

function normalizedTurnId(message: ConversationMessage) {
  return conversationMessageTurnId(message);
}

function processProjectionKey(message: ConversationMessage) {
  const turnId = normalizedTurnId(message);
  return turnId ? `turn:${turnId}` : "adjacent-process-thread";
}

function isSameTurnPacketMessage(message: ConversationMessage) {
  if (isExcludedAssistantProjectionMessage(message) || !normalizedTurnId(message)) {
    return false;
  }
  return Boolean(String(answerProjectionContent(message) ?? "").trim() || isProjectableProcessOnlyMessage(message));
}

function canMergeProcessProjection(previous: ConversationMessage | undefined, next: ConversationMessage) {
  if (!previous) {
    return false;
  }
  if (
    isSameTurnPacketMessage(previous)
    && isSameTurnPacketMessage(next)
    && normalizedTurnId(previous) === normalizedTurnId(next)
  ) {
    return true;
  }
  return Boolean(
    isProjectableProcessOnlyMessage(previous)
    && isProjectableProcessOnlyMessage(next)
    && processProjectionKey(previous) === processProjectionKey(next),
  );
}

function mergeProcessProjectionMessages(previous: ConversationMessage, next: ConversationMessage): ConversationMessage {
  return {
    ...previous,
    content: mergeText(answerProjectionContent(previous), answerProjectionContent(next)),
    streaming: Boolean(previous.streaming || next.streaming),
    streamStage: next.streamStage || previous.streamStage,
    thought: undefined,
    mentalSnapshot: undefined,
    feedbackEvents: mergeExactItems(previous.feedbackEvents, next.feedbackEvents),
    timelineItems: mergeExactItems(previous.timelineItems, next.timelineItems),
    toolCalls: undefined,
    attachments: mergeExactItems(previous.attachments, next.attachments),
    references: mergeExactItems(previous.references, next.references),
    codexTranscript: mergeCodexTranscripts(previous.codexTranscript, next.codexTranscript, previous.id),
    metadata: {
      ...(previous.metadata ?? {}),
      ...(next.metadata ?? {}),
      projectedMessageIds: [
        ...projectedConversationMessageIdsOrSelf(previous),
        ...projectedConversationMessageIdsOrSelf(next),
      ],
    },
  };
}

export function projectTimelineProcessMessages(messages: ConversationMessage[]) {
  const projected: ConversationMessage[] = [];
  for (const message of messages) {
    const previous = projected[projected.length - 1];
    if (previous && canMergeProcessProjection(previous, message)) {
      projected[projected.length - 1] = mergeProcessProjectionMessages(previous, message);
      continue;
    }
    projected.push(message);
  }
  return projected;
}
