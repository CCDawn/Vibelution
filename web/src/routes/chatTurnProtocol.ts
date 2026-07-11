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

export function visibleNativeAssistantMarkdownText(
  transcript: ConversationMessage["codexTranscript"] | undefined,
) {
  return nativeTranscriptCells(transcript)
    .filter((cell) => String(cell.kind ?? "").trim() === "assistant_markdown")
    .map((cell) => compactText(cell.text))
    .filter(Boolean)
    .join("\n\n");
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
  return compactText(surface.answerContent).length
    + compactText(surface.thoughtContent).length
    + visibleNativeAssistantMarkdownText(surface.codexTranscript).length;
}

export function resolveAssistantTurnRenderProtocol(surface: ChatTurnProtocolSurface): ChatTurnRenderProtocol {
  if (consolidateSessionTurnItemsV2(surface.turnItems).length > 0) {
    return "canonical_turn_items_v2";
  }
  if (hasVisibleNativeCodexTranscript(surface.codexTranscript)) {
    return "native_codex_transcript";
  }
  if (compactText(surface.answerContent) || compactText(surface.thoughtContent)) {
    return "legacy_assistant_delta";
  }
  return "process_feedback";
}

export function hasVisibleActiveTurnProtocolContent(surface: ChatTurnProtocolSurface) {
  return Boolean(
    consolidateSessionTurnItemsV2(surface.turnItems).length > 0
    || activeTurnProtocolTextLength(surface) > 0
    || (surface.feedbackEventCount ?? 0) > 0
    || hasVisibleNativeCodexTranscript(surface.codexTranscript)
  );
}

export function hasCommittedAssistantProtocolAnswer(message: ConversationMessage) {
  if (message.role !== "assistant") {
    return false;
  }
  const canonicalItems = consolidateSessionTurnItemsV2(message.turnItems);
  if (canonicalItems.length > 0) {
    return hasCommittedCanonicalAnswer(canonicalItems);
  }
  return Boolean(
    compactText(answerProjectionContent(message))
    || compactText(visibleNativeAssistantMarkdownText(message.codexTranscript))
  );
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

const canonicalItemIdentity = (item: CanonicalSessionTurnItem): string => [
  item.sessionId ?? "",
  item.turnId ?? "",
  item.invocationId ?? "",
  item.iteration ?? 0,
  item.itemId ?? item.id,
].join("\u001f");

const canonicalItemRevision = (item: CanonicalSessionTurnItem): number => item.revision ?? 0;
const canonicalItemSequence = (item: CanonicalSessionTurnItem): number => item.sequence ?? 0;

export const isSessionTurnItemV2 = (item: CanonicalSessionTurnItem): boolean =>
  item.version === 2 && Boolean(item.itemId);

export const consolidateSessionTurnItemsV2 = (
  ...groups: Array<readonly CanonicalSessionTurnItem[] | undefined>
): CanonicalSessionTurnItem[] => {
  const byIdentity = new Map<string, CanonicalSessionTurnItem>();
  for (const item of groups.flatMap((group) => group ?? []).filter(isSessionTurnItemV2)) {
    const identity = canonicalItemIdentity(item);
    const current = byIdentity.get(identity);
    if (
      !current
      || canonicalItemRevision(item) > canonicalItemRevision(current)
      || (
        canonicalItemRevision(item) === canonicalItemRevision(current)
        && canonicalItemSequence(item) >= canonicalItemSequence(current)
      )
    ) {
      byIdentity.set(identity, item);
    }
  }
  return [...byIdentity.values()].sort((left, right) =>
    canonicalItemSequence(left) - canonicalItemSequence(right)
    || canonicalItemIdentity(left).localeCompare(canonicalItemIdentity(right))
  );
};

const itemText = (item: CanonicalSessionTurnItem): string =>
  (item.text ?? item.summary ?? item.title ?? "").trim();

const isCanonicalAnswer = (item: CanonicalSessionTurnItem): boolean =>
  item.kind === "assistant_message"
  && item.channel === "answer"
  && item.phase === "final_answer";

const canonicalFinalAnswer = (items: readonly CanonicalSessionTurnItem[]): string =>
  items.filter(isCanonicalAnswer).map(itemText).filter(Boolean).join("\n\n");

const hasCommittedCanonicalAnswer = (items: readonly CanonicalSessionTurnItem[]): boolean =>
  items.some((item) => (
    isCanonicalAnswer(item)
    && item.provisional !== true
    && (item.terminal === true || item.status === "completed")
    && Boolean(itemText(item))
  ));

const canonicalTranscript = (
  items: readonly CanonicalSessionTurnItem[],
): CanonicalConversationMessage["codexTranscript"] => ({
  version: 1,
  source: "native",
  messageId: items[0]?.messageId ?? items[0]?.itemId ?? items[0]?.id ?? "canonical-turn-items-v2",
  cells: items.flatMap<NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]>((item) => {
    const text = itemText(item);
    if (!text) return [];
    const cellBase = {
      id: item.itemId ?? item.id,
      messageId: item.messageId ?? item.itemId ?? item.id,
      status: item.status,
      tone: "neutral",
    };
    if (isCanonicalAnswer(item)) {
      return [{ ...cellBase, kind: "assistant_markdown", markdown: text } as NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]];
    }
    if (item.kind === "reasoning" || item.channel === "analysis") {
      return [{ ...cellBase, kind: "reasoning_summary", markdown: text } as NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]];
    }
    if (item.kind === "tool_call") {
      return [{
        ...cellBase,
        kind: "tool_call",
        title: item.toolName ?? item.title ?? "Tool",
        summary: text,
        sourceItemId: item.itemId ?? item.id,
      } as NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]];
    }
    if (item.channel === "commentary") {
      return [{ ...cellBase, kind: "status", markdown: text } as NonNullable<CanonicalConversationMessage["codexTranscript"]>["cells"][number]];
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
  const nativeCells = input.codexTranscript?.cells ?? [];
  const nativeAnswer = nativeCells
    .filter((cell) => cell.kind === "assistant_markdown")
    .map((cell) => "markdown" in cell ? cell.markdown : "")
    .filter(Boolean)
    .join("\n\n");
  if (nativeAnswer) {
    return {
      protocol: "native_codex_transcript",
      answerContent: nativeAnswer,
      thoughtContent: "",
      feedbackEvents: input.feedbackEvents ?? [],
      codexTranscript: input.codexTranscript,
    };
  }
  if ((input.answerProjectionContent ?? "").trim() || (input.thoughtContent ?? "").trim()) {
    return {
      protocol: "legacy_assistant_delta",
      answerContent: input.answerProjectionContent ?? "",
      thoughtContent: input.thoughtContent ?? "",
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
