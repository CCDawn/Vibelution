import type { CodexTranscriptProjection, ConversationMessage } from "../../api/types";
import { mergeAgentFeedbackEvents } from "../../agent-thread/agentFeedbackEvents";
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

function projectionItemIdentity(value: unknown) {
  if (!value || typeof value !== "object") {
    return "exact:" + (JSON.stringify(value) ?? String(value));
  }
  const record = value as Record<string, unknown>;
  const kind = String(record.kind ?? record.type ?? "item").trim();
  for (const field of ["sourceItemId", "callId", "itemId", "id"]) {
    const stableId = String(record[field] ?? "").trim();
    if (stableId) {
      return kind + ":" + field + ":" + stableId;
    }
  }
  return "exact:" + (JSON.stringify(value) ?? String(value));
}

function mergeProjectionItems<T>(...itemGroups: Array<T[] | undefined>) {
  const merged: T[] = [];
  const indexes = new Map<string, number>();
  for (const group of itemGroups) {
    for (const item of group ?? []) {
      const key = projectionItemIdentity(item);
      const existingIndex = indexes.get(key);
      if (existingIndex !== undefined) {
        merged[existingIndex] = item;
        continue;
      }
      indexes.set(key, merged.length);
      merged.push(item);
    }
  }
  return merged.length > 0 ? merged : undefined;
}

function normalizedAssistantCellText(value: unknown) {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

function assistantCellChannel(cell: CodexTranscriptProjection["cells"][number]) {
  return String(cell.channel ?? "answer").trim() || "answer";
}

function assistantCellIsTransitional(cell: CodexTranscriptProjection["cells"][number]) {
  return Boolean(
    cell.provisional
    || cell.status === "running"
    || cell.status === "pending",
  );
}

function assistantCellRank(cell: CodexTranscriptProjection["cells"][number]) {
  return (cell.terminal ? 4 : 0)
    + (cell.provisional ? 0 : 2)
    + (cell.status === "completed" ? 2 : cell.status === "running" ? 1 : 0);
}

function assistantCellsOverlap(
  left: CodexTranscriptProjection["cells"][number],
  right: CodexTranscriptProjection["cells"][number],
) {
  if (
    left.kind !== "assistant_markdown"
    || right.kind !== "assistant_markdown"
    || assistantCellChannel(left) !== assistantCellChannel(right)
  ) {
    return false;
  }
  const leftLegacyMarkdown = "markdown" in left && typeof left.markdown === "string" ? left.markdown : "";
  const rightLegacyMarkdown = "markdown" in right && typeof right.markdown === "string" ? right.markdown : "";
  const leftText = normalizedAssistantCellText(left.text || leftLegacyMarkdown);
  const rightText = normalizedAssistantCellText(right.text || rightLegacyMarkdown);
  if (!leftText || !rightText) {
    return false;
  }
  if (leftText === rightText) {
    return true;
  }
  return (assistantCellIsTransitional(left) || assistantCellIsTransitional(right))
    && (leftText.startsWith(rightText) || rightText.startsWith(leftText));
}

type CodexTranscriptMergeOptions = {
  previousEphemeral?: boolean;
  nextEphemeral?: boolean;
  dedupeDurableToolReplays?: boolean;
};

type CodexTranscriptCellEntry = {
  cell: CodexTranscriptProjection["cells"][number];
  ephemeral: boolean;
  groupIndex: number;
};

function isEphemeralCodexTranscript(transcript: CodexTranscriptProjection | undefined) {
  const messageId = String(transcript?.messageId ?? "").trim().toLowerCase();
  return Boolean(
    transcript?.streaming
    || messageId.includes("-message-live-")
    || messageId.includes("-message-active-")
  );
}

function isEphemeralCodexTranscriptCell(cell: CodexTranscriptProjection["cells"][number]) {
  return [cell.messageId, cell.id, cell.sourceItemId]
    .map((value) => String(value ?? "").trim().toLowerCase())
    .some((value) => value.includes("-message-live-") || value.includes("-message-active-"));
}

function toolCellSemanticKey(cell: CodexTranscriptProjection["cells"][number]) {
  if (cell.kind !== "tool_call") {
    return "";
  }
  return [
    cell.kind,
    String(cell.title ?? "").replace(/\s+/g, " ").trim().toLowerCase(),
  ].join("\u001f");
}

function toolCellReplayKey(cell: CodexTranscriptProjection["cells"][number]) {
  const semanticKey = toolCellSemanticKey(cell);
  if (!semanticKey) {
    return "";
  }
  const lifecycleDetails = (cell.toolLifecycleModel?.toolCalls ?? [])
    .map((toolCall) => [
      normalizedAssistantCellText(toolCall.rawToolName ?? toolCall.title),
      normalizedAssistantCellText(toolCall.summary),
      normalizedAssistantCellText(toolCall.resultPreview),
    ].join("\u001e"))
    .join("\u001d");
  return [
    semanticKey,
    normalizedAssistantCellText(cell.summary ?? cell.text),
    lifecycleDetails,
  ].join("\u001f");
}

function mergeCodexTranscriptCellEntries(
  previous: CodexTranscriptProjection | undefined,
  next: CodexTranscriptProjection | undefined,
  options: CodexTranscriptMergeOptions,
) {
  const entries: CodexTranscriptCellEntry[] = [];
  const indexes = new Map<string, number>();
  const groups = [
    {
      cells: previous?.cells,
      ephemeral: options.previousEphemeral ?? isEphemeralCodexTranscript(previous),
    },
    {
      cells: next?.cells,
      ephemeral: options.nextEphemeral ?? isEphemeralCodexTranscript(next),
    },
  ];
  for (const [groupIndex, group] of groups.entries()) {
    for (const cell of group.cells ?? []) {
      const key = projectionItemIdentity(cell);
      const existingIndex = indexes.get(key);
      if (existingIndex === undefined) {
        indexes.set(key, entries.length);
        entries.push({
          cell,
          ephemeral: group.ephemeral || isEphemeralCodexTranscriptCell(cell),
          groupIndex,
        });
        continue;
      }
      const existing = entries[existingIndex];
      const ephemeral = group.ephemeral || isEphemeralCodexTranscriptCell(cell);
      if (!existing.ephemeral && ephemeral) {
        continue;
      }
      entries[existingIndex] = { cell, ephemeral, groupIndex };
    }
  }
  return entries;
}

function mergeCodexTranscriptCells(
  previous: CodexTranscriptProjection | undefined,
  next: CodexTranscriptProjection | undefined,
  options: CodexTranscriptMergeOptions,
) {
  const mergedEntries = mergeCodexTranscriptCellEntries(previous, next, options);
  const cells: CodexTranscriptProjection["cells"] = [];
  const cellEphemeral: boolean[] = [];
  const cellGroupIndexes: number[] = [];
  const matchedToolCells = new Set<number>();
  for (const entry of mergedEntries) {
    const { cell, ephemeral, groupIndex } = entry;
    const toolSemanticKey = toolCellSemanticKey(cell);
    if (toolSemanticKey) {
      const matchingIndex = cells.findIndex((candidate, index) => (
        !matchedToolCells.has(index)
        && toolCellSemanticKey(candidate) === toolSemanticKey
        && (
          cellEphemeral[index] !== ephemeral
          || (
            options.dedupeDurableToolReplays
            && cellGroupIndexes[index] !== groupIndex
            && toolCellReplayKey(candidate) === toolCellReplayKey(cell)
          )
        )
      ));
      if (matchingIndex >= 0) {
        matchedToolCells.add(matchingIndex);
        if (!ephemeral && cellEphemeral[matchingIndex]) {
          cells[matchingIndex] = cell;
          cellEphemeral[matchingIndex] = false;
          cellGroupIndexes[matchingIndex] = groupIndex;
        }
        continue;
      }
    }
    const overlappingIndex = cells.findIndex((candidate) => assistantCellsOverlap(candidate, cell));
    if (overlappingIndex < 0) {
      cells.push(cell);
      cellEphemeral.push(ephemeral);
      cellGroupIndexes.push(groupIndex);
      continue;
    }
    if (
      assistantCellRank(cell) > assistantCellRank(cells[overlappingIndex])
      || (
        assistantCellRank(cell) === assistantCellRank(cells[overlappingIndex])
        && cellEphemeral[overlappingIndex]
        && !ephemeral
      )
    ) {
      cells[overlappingIndex] = cell;
      cellEphemeral[overlappingIndex] = ephemeral;
      cellGroupIndexes[overlappingIndex] = groupIndex;
    }
  }
  return cells;
}

type ConversationFeedbackEvent = NonNullable<ConversationMessage["feedbackEvents"]>[number];

function mergeProjectionFeedbackEvents(
  ...eventGroups: Array<ConversationMessage["feedbackEvents"]>
) {
  const merged: ConversationFeedbackEvent[] = [];
  const callIndexes = new Map<string, number>();
  const exactKeys = new Set<string>();
  for (const group of eventGroups) {
    for (const event of group ?? []) {
      const callId = String(event.callId ?? "").trim();
      if (callId) {
        const existingIndex = callIndexes.get(callId);
        if (existingIndex !== undefined) {
          const consolidated = mergeAgentFeedbackEvents([merged[existingIndex]], [event]) ?? [];
          merged[existingIndex] = consolidated[0] ?? event;
          continue;
        }
        callIndexes.set(callId, merged.length);
        merged.push(event);
        continue;
      }
      const exactKey = JSON.stringify(event);
      if (exactKeys.has(exactKey)) {
        continue;
      }
      exactKeys.add(exactKey);
      merged.push(event);
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

export function mergeCodexTranscripts(
  previous: CodexTranscriptProjection | undefined,
  next: CodexTranscriptProjection | undefined,
  messageId: string,
  options: CodexTranscriptMergeOptions = {},
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
    streaming: next.streaming ?? previous.streaming,
    cells: mergeCodexTranscriptCells(previous, next, options),
    rolloutEvents: mergeProjectionItems(previous.rolloutEvents, next.rolloutEvents),
    toolCalls: mergeProjectionItems(previous.toolCalls, next.toolCalls) ?? [],
    terminalOperations: mergeProjectionItems(previous.terminalOperations, next.terminalOperations) ?? [],
    terminalSessions: mergeProjectionItems(previous.terminalSessions, next.terminalSessions) ?? [],
    modelObservations: mergeProjectionItems(previous.modelObservations, next.modelObservations) ?? [],
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
  const durableToolReplayBoundary = isDurableToolReplayBoundary(previous, next);
  const previousTranscript = durableToolReplayBoundary ? next.codexTranscript : previous.codexTranscript;
  const nextTranscript = durableToolReplayBoundary ? previous.codexTranscript : next.codexTranscript;
  const previousTranscriptMessage = durableToolReplayBoundary ? next : previous;
  const nextTranscriptMessage = durableToolReplayBoundary ? previous : next;
  return {
    ...previous,
    content: mergeText(answerProjectionContent(previous), answerProjectionContent(next)),
    streaming: next.streaming ?? previous.streaming,
    streamStage: next.streamStage || previous.streamStage,
    thought: undefined,
    mentalSnapshot: undefined,
    feedbackEvents: mergeProjectionFeedbackEvents(previous.feedbackEvents, next.feedbackEvents),
    timelineItems: mergeProjectionItems(previous.timelineItems, next.timelineItems),
    toolCalls: undefined,
    attachments: mergeProjectionItems(previous.attachments, next.attachments),
    references: mergeProjectionItems(previous.references, next.references),
    codexTranscript: mergeCodexTranscripts(previousTranscript, nextTranscript, previous.id, {
      previousEphemeral: isEphemeralProjectionMessage(previousTranscriptMessage),
      nextEphemeral: isEphemeralProjectionMessage(nextTranscriptMessage),
      dedupeDurableToolReplays: durableToolReplayBoundary,
    }),
    metadata: {
      ...(previous.metadata ?? {}),
      ...(next.metadata ?? {}),
      projectedMessageIds: [...new Set([
        ...projectedConversationMessageIdsOrSelf(previous),
        ...projectedConversationMessageIdsOrSelf(next),
      ])],
    },
  };
}

function isDurableToolReplayBoundary(previous: ConversationMessage, next: ConversationMessage) {
  return Boolean(
    !isEphemeralProjectionMessage(previous)
    && !isEphemeralProjectionMessage(next)
    && String(previous.metadata?.kind ?? "").trim() === "tool_result"
    && String(next.metadata?.kind ?? "").trim() === "assistant_item_committed"
    && String(answerProjectionContent(next) ?? "").trim(),
  );
}

function isEphemeralProjectionMessage(message: ConversationMessage) {
  const kind = String(message.metadata?.kind ?? "").trim();
  return Boolean(
    message.streaming
    || kind === "session_live_overlay"
    || kind === "session_active_turn_layer"
  );
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
