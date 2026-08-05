import type { ConversationMessage } from "../api/types";
import { shouldDisplayTranscriptCell } from "../components/conversation/conversationDisplayProtocol";
import { answerProjectionContent } from "../components/conversation/conversationInternalStatus";

export type ChatTurnRenderProtocol =
  | "canonical_turn_items_v2"
  | "legacy_assistant_delta"
  | "native_codex_transcript"
  | "process_feedback";

export type ChatTurnProtocolSurface = {
  answerContent?: unknown;
  thoughtContent?: unknown;
  feedbackEventCount?: number;
  codexTranscript?: ConversationMessage["codexTranscript"];
  turnItems?: ConversationMessage["turnItems"];
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function nativeTranscriptCells(transcript: ConversationMessage["codexTranscript"] | undefined) {
  if (
    !transcript
    || String(transcript.source ?? "").trim() !== "native"
    || !Array.isArray(transcript.cells)
  ) {
    return [];
  }
  return transcript.cells.filter(shouldDisplayTranscriptCell);
}

function compactProjectionKey(value: unknown) {
  return String(value ?? "").replace(/\s+/g, "").trim();
}

function isCommentaryPhase(value: unknown) {
  const phase = compactText(value).toLowerCase();
  return phase === "commentary" || phase === "interim";
}

function isExplicitFinalAnswerCell(cell: { phase?: unknown; terminal?: unknown; provisional?: unknown }) {
  if (cell.provisional === true) {
    return false;
  }
  const phase = compactText(cell.phase).toLowerCase();
  return phase === "final_answer" || cell.terminal === true;
}

function isCommittedNativeAssistantCell(cell: {
  phase?: unknown;
  status?: unknown;
  provisional?: unknown;
  terminal?: unknown;
}) {
  if (cell.provisional === true || isCommentaryPhase(cell.phase)) {
    return false;
  }
  const status = compactText(cell.status).toLowerCase();
  if (["pending", "running", "in_progress", "streaming"].includes(status)) {
    return false;
  }
  return Boolean(
    isExplicitFinalAnswerCell(cell)
    || !status
    || ["completed", "done"].includes(status),
  );
}

/** Prefer explicit final_answer / terminal cells; otherwise all non-commentary markdown. */
export function visibleNativeFinalAnswerText(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  const cells = nativeTranscriptCells(transcript)
    .filter((cell) => String(cell.kind ?? "").trim() === "assistant_markdown")
    .filter((cell) => compactText(cell.text))
    .filter((cell) => !isCommentaryPhase(cell.phase));
  const explicit = cells.filter((cell) => isExplicitFinalAnswerCell(cell));
  const chosen = explicit.length > 0 ? explicit : cells;
  return chosen.map((cell) => compactText(cell.text)).filter(Boolean).join("\n\n");
}

export function visibleNativeAssistantMarkdownText(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  return nativeTranscriptCells(transcript)
    .filter((cell) => String(cell.kind ?? "").trim() === "assistant_markdown")
    .map((cell) => compactText(cell.text))
    .filter(Boolean)
    .join("\n\n");
}

/**
 * True when native answer text already owns the committed final answer body.
 * Short orphan capture fragments (e.g. "存。") must not win over long content.
 */
export function nativeAnswerOwnsProjectedContent(
  nativeAnswer: string,
  projectedAnswer: string,
  options?: { hasExplicitFinalCell?: boolean },
) {
  const nativeKey = compactProjectionKey(nativeAnswer);
  const contentKey = compactProjectionKey(projectedAnswer);
  if (!nativeKey) {
    return false;
  }
  if (options?.hasExplicitFinalCell) {
    return true;
  }
  if (!contentKey) {
    return true;
  }
  if (contentKey === nativeKey || nativeKey.includes(contentKey)) {
    return true;
  }
  if (
    contentKey.includes(nativeKey)
    && nativeKey.length >= Math.max(24, Math.floor(contentKey.length * 0.8))
  ) {
    return true;
  }
  if (nativeKey.length < Math.max(8, Math.floor(contentKey.length * 0.5))) {
    return false;
  }
  return true;
}

export function hasVisibleNativeCodexTranscript(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  return nativeTranscriptCells(transcript).length > 0;
}

export function activeTurnProtocolTextLength(surface: ChatTurnProtocolSurface) {
  const canonicalItems = consolidateSessionTurnItemsV2(surface.turnItems);
  if (canonicalItems.length > 0) {
    return canonicalFinalAnswer(canonicalItems).length;
  }
  const projected = compactText(surface.answerContent);
  const nativeFinal = visibleNativeFinalAnswerText(surface.codexTranscript);
  // Prefer the longer of projected content vs native final to avoid orphan-only length.
  const answerLen = Math.max(projected.length, nativeFinal.length);
  return answerLen + compactText(surface.thoughtContent).length;
}

export function resolveAssistantTurnRenderProtocol(surface: ChatTurnProtocolSurface): ChatTurnRenderProtocol {
  return resolveAssistantTurnRenderSurface({
    answerProjectionContent: surface.answerContent == null ? undefined : String(surface.answerContent),
    thoughtContent: surface.thoughtContent == null ? undefined : String(surface.thoughtContent),
    feedbackEvents: surface.feedbackEventCount ? Array.from({ length: surface.feedbackEventCount }) : [],
    codexTranscript: surface.codexTranscript,
    turnItems: surface.turnItems,
  }).protocol;
}

export function hasVisibleActiveTurnProtocolContent(surface: ChatTurnProtocolSurface) {
  return Boolean(
    consolidateSessionTurnItemsV2(surface.turnItems).length > 0
    || activeTurnProtocolTextLength(surface) > 0
    || (surface.feedbackEventCount ?? 0) > 0
    || hasVisibleNativeCodexTranscript(surface.codexTranscript)
  );
}

function isNonTerminalAssistantProjection(message: ConversationMessage) {
  const kind = compactText(message.metadata?.kind).toLowerCase();
  return Boolean(
    message.streaming
    || kind === "journal_assistant_partial"
    || kind === "session_live_overlay"
    || kind === "session_active_turn_layer"
  );
}

export function hasCommittedAssistantProtocolAnswer(message: ConversationMessage) {
  if (message.role !== "assistant" || isNonTerminalAssistantProjection(message)) {
    return false;
  }
  const canonicalItems = consolidateSessionTurnItemsV2(message.turnItems);
  if (canonicalItems.length > 0) {
    return hasCommittedCanonicalAnswer(canonicalItems);
  }
  const projected = compactText(answerProjectionContent(message));
  const nativeAssistantCells = nativeTranscriptCells(message.codexTranscript)
    .filter((cell) => String(cell.kind ?? "").trim() === "assistant_markdown")
    .filter((cell) => compactText(cell.text));
  const explicitFinalCells = nativeAssistantCells.filter((cell) => isExplicitFinalAnswerCell(cell));
  if (explicitFinalCells.length > 0) {
    return true;
  }
  const committedNative = nativeAssistantCells.filter((cell) => isCommittedNativeAssistantCell(cell));
  if (committedNative.length > 0) {
    const nativeText = committedNative.map((cell) => compactText(cell.text)).filter(Boolean).join("\n\n");
    // Orphan completed fragments must not count as "committed answer" when content is the real body.
    if (nativeAnswerOwnsProjectedContent(nativeText, projected)) {
      return true;
    }
  }
  return Boolean(projected);
}
import type {
  ConversationMessage as CanonicalConversationMessage,
  SessionTurnItem as CanonicalSessionTurnItem,
} from "../api/types/chat";

type CanonicalTurnRenderSurface = {
  protocol: "canonical_turn_items_v2" | "native_codex_transcript" | "legacy_assistant_delta" | "process_feedback";
  answerContent: string;
  thoughtContent: string;
  feedbackEvents: unknown[];
  codexTranscript?: CanonicalConversationMessage["codexTranscript"];
  turnItems?: CanonicalSessionTurnItem[];
};

const canonicalItemIdentity = (item: CanonicalSessionTurnItem): string => {
  const callId = compactText(item.callId);
  const itemId = compactText(item.itemId ?? item.id);
  return [
    item.sessionId ?? "",
    item.turnId ?? "",
    callId ? "call:" + callId : "item:" + itemId,
  ].join("\u001f");
};

const canonicalItemRevision = (item: CanonicalSessionTurnItem): number => item.revision ?? 0;
const canonicalItemSequence = (item: CanonicalSessionTurnItem): number => item.sequence ?? 0;

const shouldReplaceCanonicalItem = (
  current: CanonicalSessionTurnItem,
  candidate: CanonicalSessionTurnItem,
) => (
  canonicalItemRevision(candidate) > canonicalItemRevision(current)
  || (
    canonicalItemRevision(candidate) === canonicalItemRevision(current)
    && canonicalItemSequence(candidate) >= canonicalItemSequence(current)
  )
);

export const isSessionTurnItemV2 = (item: CanonicalSessionTurnItem): boolean =>
  item.version === 2 && Boolean(item.itemId);

export const consolidateSessionTurnItemsV2 = (
  ...groups: Array<readonly CanonicalSessionTurnItem[] | undefined>
): CanonicalSessionTurnItem[] => {
  const byIdentity = new Map<string, {
    item: CanonicalSessionTurnItem;
    firstSequence: number;
    firstIndex: number;
  }>();
  const candidates = groups.flatMap((group) => group ?? []).filter(isSessionTurnItemV2);
  candidates.forEach((item, firstIndex) => {
    const identity = canonicalItemIdentity(item);
    const current = byIdentity.get(identity);
    if (!current) {
      byIdentity.set(identity, {
        item,
        firstSequence: canonicalItemSequence(item),
        firstIndex,
      });
      return;
    }
    const firstSequence = Math.min(current.firstSequence, canonicalItemSequence(item));
    byIdentity.set(identity, {
      ...current,
      item: shouldReplaceCanonicalItem(current.item, item) ? item : current.item,
      firstSequence,
    });
  });
  return [...byIdentity.entries()]
    .sort(([leftIdentity, left], [rightIdentity, right]) =>
      left.firstSequence - right.firstSequence
      || left.firstIndex - right.firstIndex
      || leftIdentity.localeCompare(rightIdentity)
    )
    .map(([, entry]) => entry.item);
};

const itemText = (item: CanonicalSessionTurnItem): string =>
  (item.text ?? item.summary ?? item.title ?? "").trim();

const isCanonicalAnswer = (item: CanonicalSessionTurnItem): boolean =>
  item.kind === "assistant_message"
  && item.channel === "answer"
  && item.phase === "final_answer";

const canonicalFinalAnswer = (items: readonly CanonicalSessionTurnItem[]): string =>
  items.filter(isCanonicalAnswer).map(itemText).filter(Boolean).join("\n\n");

const isCanonicalCommentary = (item: CanonicalSessionTurnItem): boolean =>
  item.kind === "commentary"
  || item.channel === "commentary"
  || item.channel === "interim"
  || item.phase === "commentary"
  || item.phase === "interim";

const canonicalDisplayChannel = (item: CanonicalSessionTurnItem) =>
  isCanonicalCommentary(item) ? "commentary" : item.channel;

const canonicalDisplayPhase = (item: CanonicalSessionTurnItem) =>
  isCanonicalCommentary(item) ? "commentary" : item.phase;

const canonicalRenderItemId = (item: CanonicalSessionTurnItem) =>
  compactText(item.callId)
  || compactText(item.itemId)
  || compactText(item.id);

const hasCommittedCanonicalAnswer = (items: readonly CanonicalSessionTurnItem[]): boolean =>
  items.some((item) => (
    isCanonicalAnswer(item)
    && item.provisional !== true
    && (item.terminal === true || item.status === "completed")
    && Boolean(itemText(item))
  ));

const canonicalCellTone = (item: CanonicalSessionTurnItem) => {
  if (item.status === "failed") return "error" as const;
  if (item.status === "degraded") return "warning" as const;
  if (
    item.status === "running"
    || item.status === "in_progress"
    || item.status === "pending"
  ) {
    return "running" as const;
  }
  return "neutral" as const;
};

export const hasTerminalCanonicalTurnOutcome = (
  message: CanonicalConversationMessage,
): boolean =>
  consolidateSessionTurnItemsV2(message.turnItems).some((item) => (
    item.terminal === true
    && item.provisional !== true
    && (item.status === "completed" || item.status === "failed")
  ));

const canonicalTranscript = (
  items: readonly CanonicalSessionTurnItem[],
): CanonicalConversationMessage["codexTranscript"] => ({
  version: 1,
  source: "native",
  messageId: items[0]?.messageId || (items[0] ? canonicalRenderItemId(items[0]) : "canonical-turn-items-v2"),
  cells: items.flatMap<NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]>((item) => {
    const text = itemText(item);
    if (!text) return [];
    const renderItemId = canonicalRenderItemId(item);
    const cellBase = {
      id: renderItemId,
      messageId: item.messageId ?? renderItemId,
      status: item.status,
      tone: canonicalCellTone(item),
      channel: canonicalDisplayChannel(item),
      phase: canonicalDisplayPhase(item),
      terminal: item.terminal,
      provisional: item.provisional,
      diagnosticSummary: item.diagnosticSummary,
      sourceItemId: item.sourceItemId ?? renderItemId,
    };
    if (isCanonicalAnswer(item)) {
      return [{ ...cellBase, kind: "assistant_markdown", text }];
    }
    if (item.kind === "reasoning" || item.channel === "analysis") {
      return [{ ...cellBase, kind: "reasoning_summary", text }];
    }
    if (item.kind === "tool_call") {
      return [{
        ...cellBase,
        kind: "tool_call",
        title: item.toolName ?? item.title ?? "Tool",
        text,
        summary: item.summary,
      }];
    }
    if (item.kind === "error" || item.type === "error") {
      return [{
        ...cellBase,
        kind: "error_notice",
        tone: "error",
        text,
        terminal: true,
      }];
    }
    if (item.kind === "status" || item.type === "status") {
      return [{ ...cellBase, kind: "status", text }];
    }
    if (isCanonicalCommentary(item)) {
      return [{ ...cellBase, kind: "assistant_markdown", text }];
    }
    return [];
  }),
  toolCalls: [],
  terminalOperations: [],
  terminalSessions: [],
  modelObservations: [],
});

export const resolveAssistantTurnRenderSurface = (input: {
  answerProjectionContent?: string;
  thoughtContent?: string;
  feedbackEvents?: unknown[];
  codexTranscript?: CanonicalConversationMessage["codexTranscript"];
  turnItems?: CanonicalSessionTurnItem[];
}): CanonicalTurnRenderSurface => {
  const turnItems = consolidateSessionTurnItemsV2(input.turnItems);
  if (turnItems.length > 0) {
    return {
      protocol: "canonical_turn_items_v2",
      answerContent: canonicalFinalAnswer(turnItems),
      thoughtContent: "",
      feedbackEvents: input.feedbackEvents ?? [],
      codexTranscript: canonicalTranscript(turnItems),
      turnItems,
    };
  }
  const projectedAnswer = compactText(input.answerProjectionContent);
  const thoughtContent = compactText(input.thoughtContent);
  const nativeCells = nativeTranscriptCells(input.codexTranscript);
  const hasExplicitFinalCell = nativeCells.some((cell) => (
    String(cell.kind ?? "").trim() === "assistant_markdown"
    && compactText(cell.text)
    && isExplicitFinalAnswerCell(cell)
  ));
  const nativeFinalAnswer = visibleNativeFinalAnswerText(input.codexTranscript);
  // Prefer explicit final / covering native answer. Orphan fragments lose to projected content.
  if (
    nativeFinalAnswer
    && nativeAnswerOwnsProjectedContent(nativeFinalAnswer, projectedAnswer, { hasExplicitFinalCell })
  ) {
    return {
      protocol: "native_codex_transcript",
      answerContent: nativeFinalAnswer,
      thoughtContent: "",
      feedbackEvents: input.feedbackEvents ?? [],
      codexTranscript: input.codexTranscript,
    };
  }
  if (projectedAnswer || thoughtContent) {
    return {
      protocol: "legacy_assistant_delta",
      answerContent: projectedAnswer || (input.answerProjectionContent ?? ""),
      thoughtContent: thoughtContent || (input.thoughtContent ?? ""),
      feedbackEvents: input.feedbackEvents ?? [],
      // Keep native transcript for process rendering; answer body comes from content.
      codexTranscript: input.codexTranscript,
    };
  }
  if (hasVisibleNativeCodexTranscript(input.codexTranscript)) {
    return {
      protocol: "native_codex_transcript",
      answerContent: nativeFinalAnswer,
      thoughtContent: "",
      feedbackEvents: input.feedbackEvents ?? [],
      codexTranscript: input.codexTranscript,
    };
  }
  return {
    protocol: "process_feedback",
    answerContent: "",
    thoughtContent: "",
    feedbackEvents: input.feedbackEvents ?? [],
    codexTranscript: input.codexTranscript,
  };
};

/**
 * Project an existing SessionTurnItem v2 package into content + codexTranscript.
 *
 * Legacy messages without turnItems are left unchanged: backend detail/window now
 * attaches turnItems (including content fallback). Remaining package-less rows are
 * process-only / status placeholders and intentionally use legacy rails.
 */
export const projectConversationMessageFromTurnItemsV2 = <T extends CanonicalConversationMessage>(message: T): T => {
  const turnItems = consolidateSessionTurnItemsV2(message.turnItems);
  if (turnItems.length === 0) return message;
  return {
    ...message,
    content: canonicalFinalAnswer(turnItems),
    thought: undefined,
    turnItems,
    codexTranscript: canonicalTranscript(turnItems),
  };
};
