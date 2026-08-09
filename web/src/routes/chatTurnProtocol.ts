import type {
  CodexTranscriptProjection,
  ConversationMessage,
  SessionTurnItem,
} from "../api/types/chat";

/** The transport label is retained; the render protocol is now only TurnItems. */
export type ChatTurnRenderProtocol = "turn_items" | "empty";

export type ChatTurnProtocolSurface = {
  turnItems?: readonly SessionTurnItem[];
};

type CanonicalTurnRenderSurface = {
  protocol: ChatTurnRenderProtocol;
  answerContent: string;
  thoughtContent: string;
  codexTranscript: CodexTranscriptProjection;
  turnItems: SessionTurnItem[];
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

const canonicalItemIdentity = (item: SessionTurnItem): string => [
  item.sessionId,
  item.turnId,
  item.type === "tool_call" ? `call:${item.callId}` : `item:${item.itemId}`,
].join("\u001f");

const shouldReplaceCanonicalItem = (current: SessionTurnItem, candidate: SessionTurnItem) => (
  candidate.revision > current.revision
  || (candidate.revision === current.revision && candidate.sequence >= current.sequence)
);

export const isSessionTurnItemV2 = (item: SessionTurnItem): boolean => (
  item.version === 3
  && Boolean(item.id)
  && Boolean(item.itemId)
  && Boolean(item.sessionId)
  && Boolean(item.turnId)
);

/**
 * Merge stream frames by stable item identity.  A later revision replaces one
 * item only; no text field is concatenated outside the item that owns it.
 */
export const consolidateSessionTurnItemsV2 = (
  ...groups: Array<readonly SessionTurnItem[] | undefined>
): SessionTurnItem[] => {
  const byIdentity = new Map<string, { item: SessionTurnItem; firstIndex: number }>();
  groups.flatMap((group) => group ?? []).filter(isSessionTurnItemV2).forEach((item, index) => {
    const identity = canonicalItemIdentity(item);
    const current = byIdentity.get(identity);
    if (!current || shouldReplaceCanonicalItem(current.item, item)) {
      byIdentity.set(identity, { item, firstIndex: current?.firstIndex ?? index });
    }
  });
  return [...byIdentity.entries()]
    .sort(([leftIdentity, left], [rightIdentity, right]) => (
      left.item.sequence - right.item.sequence
      || left.firstIndex - right.firstIndex
      || leftIdentity.localeCompare(rightIdentity)
    ))
    .map(([, entry]) => entry.item);
};

export const isFinalAnswerTurnItem = (
  item: SessionTurnItem,
): item is Extract<SessionTurnItem, { type: "agent_message" }> => (
  item.type === "agent_message" && item.phase === "final_answer"
);

export const finalAnswerTextFromTurnItems = (items: readonly SessionTurnItem[]) => (
  items
    .filter(isFinalAnswerTurnItem)
    .map((item) => item.text.trim())
    .filter(Boolean)
    .join("\n\n")
);

export const reasoningTextFromTurnItems = (items: readonly SessionTurnItem[]) => (
  items
    .filter((item) => item.type === "reasoning")
    .map((item) => item.text.trim())
    .filter(Boolean)
    .join("\n\n")
);

/** The only ConversationMessage selector for assistant-owned process data. */
export const assistantTurnItemsForMessage = (message: ConversationMessage): SessionTurnItem[] => (
  message.role === "assistant" ? consolidateSessionTurnItemsV2(message.turnItems) : []
);

export const assistantTurnIsStreaming = (message: ConversationMessage): boolean => (
  message.role === "assistant" && message.status === "running"
);

export const assistantFinalAnswerText = (message: ConversationMessage): string => (
  message.role === "assistant" ? finalAnswerTextFromTurnItems(message.turnItems) : ""
);

export const assistantReasoningText = (message: ConversationMessage): string => (
  message.role === "assistant" ? reasoningTextFromTurnItems(message.turnItems) : ""
);

export const assistantStatusTurnItems = (message: ConversationMessage): Array<Extract<SessionTurnItem, { type: "status" | "retry" | "error" }>> => (
  assistantTurnItemsForMessage(message).filter((item): item is Extract<SessionTurnItem, { type: "status" | "retry" | "error" }> => (
    item.type === "status" || item.type === "retry" || item.type === "error"
  ))
);

export const assistantToolCallTurnItems = (message: ConversationMessage): Array<Extract<SessionTurnItem, { type: "tool_call" }>> => (
  assistantTurnItemsForMessage(message).filter((item): item is Extract<SessionTurnItem, { type: "tool_call" }> => item.type === "tool_call")
);

function cellTone(item: SessionTurnItem): "neutral" | "running" | "warning" | "error" {
  if (item.status === "failed" || item.type === "error") return "error";
  if (item.status === "pending" || item.status === "running") return "running";
  return "neutral";
}

/** A local renderer projection. It is never stored back on ConversationMessage. */
export function codexTranscriptFromTurnItems(
  items: readonly SessionTurnItem[],
): CodexTranscriptProjection {
  const cells = items.flatMap<CodexTranscriptProjection["cells"][number]>((item) => {
    const base = {
      // Revisions replace one logical row; the renderer key must stay on the
      // stable item identity instead of remounting for every streamed frame.
      id: item.itemId,
      messageId: item.itemId,
      status: item.status,
      tone: cellTone(item),
      phase: item.type === "agent_message" ? item.phase : undefined,
      terminal: item.terminal,
      diagnosticSummary: item.diagnosticSummary,
      sourceItemId: item.itemId,
    };
    if (item.type === "agent_message") {
      return item.text.trim() ? [{ ...base, kind: "assistant_markdown", text: item.text }] : [];
    }
    if (item.type === "reasoning") {
      return item.text.trim() ? [{ ...base, kind: "reasoning_summary", text: item.text }] : [];
    }
    if (item.type === "tool_call") {
      return [{
        ...base,
        kind: "tool_call",
        title: item.toolName,
        text: item.output,
        summary: item.summary,
      }];
    }
    if (item.type === "retry") {
      return [{ ...base, kind: "status", title: "model_retry", text: item.reason, summary: item.reason }];
    }
    if (item.type === "status") {
      return [{ ...base, kind: "status", title: item.code, text: item.text, summary: item.summary }];
    }
    return [{ ...base, kind: "error_notice", tone: "error", title: item.code, text: item.text, summary: item.summary }];
  });
  return {
    version: 1,
    source: "native",
    messageId: items[0]?.itemId || "turn-items",
    cells,
    toolCalls: [],
    terminalOperations: [],
    terminalSessions: [],
    modelObservations: [],
  };
}

export const resolveAssistantTurnRenderSurface = (
  input: ChatTurnProtocolSurface,
): CanonicalTurnRenderSurface => {
  const turnItems = consolidateSessionTurnItemsV2(input.turnItems);
  return {
    protocol: turnItems.length > 0 ? "turn_items" : "empty",
    answerContent: finalAnswerTextFromTurnItems(turnItems),
    thoughtContent: reasoningTextFromTurnItems(turnItems),
    codexTranscript: codexTranscriptFromTurnItems(turnItems),
    turnItems,
  };
};

export function resolveAssistantTurnRenderProtocol(surface: ChatTurnProtocolSurface): ChatTurnRenderProtocol {
  return resolveAssistantTurnRenderSurface(surface).protocol;
}

export function activeTurnProtocolTextLength(surface: ChatTurnProtocolSurface) {
  const resolved = resolveAssistantTurnRenderSurface(surface);
  return resolved.answerContent.length + resolved.thoughtContent.length;
}

export function hasVisibleActiveTurnProtocolContent(surface: ChatTurnProtocolSurface) {
  return consolidateSessionTurnItemsV2(surface.turnItems).length > 0;
}

export function hasCommittedAssistantProtocolAnswer(message: ConversationMessage) {
  if (message.role !== "assistant" || message.status !== "completed") return false;
  return consolidateSessionTurnItemsV2(message.turnItems).some((item) => (
    isFinalAnswerTurnItem(item)
    && item.status === "completed"
    && item.terminal === true
    && Boolean(item.text.trim())
  ));
}

export const hasTerminalCanonicalTurnOutcome = (message: ConversationMessage): boolean => (
  message.role === "assistant"
  && (message.status === "completed" || message.status === "failed")
  && consolidateSessionTurnItemsV2(message.turnItems).some((item) => (
    item.terminal === true && (item.status === "completed" || item.status === "failed")
  ))
);

/** Normalize only the canonical item sequence; never create legacy display fields. */
export const projectConversationMessageFromTurnItemsV2 = (
  message: ConversationMessage,
): ConversationMessage => (
  message.role === "assistant"
    ? { ...message, turnItems: consolidateSessionTurnItemsV2(message.turnItems) }
    : message
);
