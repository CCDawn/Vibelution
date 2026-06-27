import type { ConversationMessage } from "../../api/types";
import {
  isGroupRoomTranscriptMessage,
  isRuntimeNoticeMessage,
  isTurnErrorMessage,
} from "./messageSections";

function metadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value).trim();
  }
  return "";
}

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
  const seen = new Set<string>();
  for (const value of values) {
    const text = String(value ?? "").trim();
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    merged.push(text);
  }
  return merged.join("\n\n");
}

function projectedMessageIds(message: ConversationMessage) {
  const existing = message.metadata?.projectedMessageIds;
  if (Array.isArray(existing)) {
    return existing.map((item) => String(item)).filter(Boolean);
  }
  return [message.id];
}

function isCliAgentLifecycleMessage(message: ConversationMessage) {
  return metadataText(message.metadata, "kind") === "cli_agent_lifecycle";
}

function isProjectableProcessOnlyMessage(message: ConversationMessage) {
  if (
    message.role !== "assistant"
    || isRuntimeNoticeMessage(message)
    || isCliAgentLifecycleMessage(message)
    || isGroupRoomTranscriptMessage(message)
    || isTurnErrorMessage(message)
    || String(message.content ?? "").trim()
  ) {
    return false;
  }
  return Boolean(
    String(message.streamStage ?? "").trim()
    || (message.feedbackEvents?.length ?? 0) > 0
    || (message.timelineItems?.length ?? 0) > 0
    || (message.toolCalls?.length ?? 0) > 0
    || String(message.thought ?? "").trim()
    || message.mentalSnapshot,
  );
}

function processProjectionKey(message: ConversationMessage) {
  const turnId = metadataText(message.metadata, "turnId").replace(/^live:/, "");
  return turnId ? `turn:${turnId}` : "adjacent-process-thread";
}

function canMergeProcessProjection(previous: ConversationMessage | undefined, next: ConversationMessage) {
  return Boolean(
    previous
    && isProjectableProcessOnlyMessage(previous)
    && isProjectableProcessOnlyMessage(next)
    && processProjectionKey(previous) === processProjectionKey(next),
  );
}

function mergeProcessProjectionMessages(previous: ConversationMessage, next: ConversationMessage): ConversationMessage {
  return {
    ...previous,
    streaming: Boolean(previous.streaming || next.streaming),
    streamStage: next.streamStage || previous.streamStage,
    thought: mergeText(previous.thought, next.thought) || undefined,
    mentalSnapshot: next.mentalSnapshot ?? previous.mentalSnapshot,
    feedbackEvents: mergeExactItems(previous.feedbackEvents, next.feedbackEvents),
    timelineItems: mergeExactItems(previous.timelineItems, next.timelineItems),
    toolCalls: mergeExactItems(previous.toolCalls, next.toolCalls),
    attachments: mergeExactItems(previous.attachments, next.attachments),
    references: mergeExactItems(previous.references, next.references),
    metadata: {
      ...(previous.metadata ?? {}),
      ...(next.metadata ?? {}),
      projectedMessageIds: [
        ...projectedMessageIds(previous),
        ...projectedMessageIds(next),
      ],
    },
  };
}

export function projectConversationProcessMessages(messages: ConversationMessage[]) {
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
