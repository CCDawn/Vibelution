/**
 * Single display-plan resolver for assistant turns.
 *
 * Phase C: when SessionTurnItem v2 package exists, ConversationView renders one
 * cells track (codexTranscript derived from items). Legacy response/timeline
 * answer paths are fallback only.
 */
import type { ConversationMessage } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  nativeAnswerOwnsProjectedContent,
  resolveAssistantTurnRenderSurface,
  type ChatTurnRenderProtocol,
} from "../../routes/chatTurnProtocol";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import {
  answerProjectionContent,
  timelineAssistantTextCoversFinalAnswer,
} from "./conversationInternalStatus";
import { shouldRenderCodexTranscriptSurface } from "./conversationOperationPresentation";

export type AssistantAnswerOwner =
  | "canonical_turn_items"
  | "native_transcript"
  | "timeline_assistant_text"
  | "response_section"
  | "none";

export type AssistantRenderMode =
  /** turnItems package → cells only (primary path) */
  | "package_cells"
  /** native transcript without v2 package */
  | "native_transcript"
  /** legacy timeline + response */
  | "legacy";

export type AssistantDisplayPlan = {
  protocol: ChatTurnRenderProtocol;
  renderMode: AssistantRenderMode;
  /** True when message.turnItems has SessionTurnItem v2 rows. */
  hasTurnItemPackage: boolean;
  /** Who owns the committed final answer body for this turn. */
  answerOwner: AssistantAnswerOwner;
  nativePrimary: boolean;
  nativeOwnsFinalAnswer: boolean;
  timelineOwnsFinalAnswer: boolean;
  /**
   * Whether timeline builders should append/include assistant_text from content.
   * Always false in package_cells mode.
   */
  includeTimelineAssistantText: boolean;
  /**
   * Drop pure assistant_text server timeline when package/native owns the body.
   */
  omitAssistantOnlyServerTimeline: boolean;
  /**
   * When package mode, strip assistant_text from server timeline so process
   * timeline cannot re-render answer rows.
   */
  stripTimelineAssistantText: boolean;
  suppressProjectedResponse: boolean;
  suppressProjectedProcess: boolean;
  suppressProjectedTurnStatus: boolean;
  suppressProjectedError: boolean;
  /** Native/package answer is primary and process may still render via timeline rail. */
  shouldRenderNativeProcessAlongsideAnswer: boolean;
  shouldRenderCodexSurface: boolean;
};

type TimelineLikeItem = {
  kind?: string;
  text?: string;
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

function surfaceNativeOwnsFinalAnswer(
  surface: CodexTranscriptSurface | undefined,
  projectedAnswer: string,
) {
  if (!surface || surface.mode !== "native") {
    return false;
  }
  const answerCells = surface.cells.filter((cell) => (
    cell.kind === "assistant_markdown"
    && Boolean(cell.text?.trim())
    && String(cell.phase ?? "").trim().toLowerCase() !== "commentary"
  ));
  if (answerCells.length === 0) {
    return false;
  }
  const hasExplicitFinalCell = answerCells.some((cell) => {
    const phase = String(cell.phase ?? "").trim().toLowerCase();
    return phase === "final_answer" || cell.terminal === true;
  });
  const nativeAnswer = answerCells
    .map((cell) => String(cell.text ?? "").trim())
    .filter(Boolean)
    .join("\n\n");
  return nativeAnswerOwnsProjectedContent(nativeAnswer, projectedAnswer, { hasExplicitFinalCell });
}

function serverTimelineIsAssistantTextOnly(items: readonly TimelineLikeItem[] | undefined) {
  const list = items ?? [];
  if (list.length === 0) {
    return false;
  }
  return list.every((item) => String(item.kind ?? "").trim() === "assistant_text");
}

/** Filter assistant_text rows out of server timeline for package/native ownership modes. */
export function filterServerTimelineItemsForDisplayPlan(
  items: readonly TimelineLikeItem[] | undefined,
  plan: Pick<AssistantDisplayPlan, "stripTimelineAssistantText" | "omitAssistantOnlyServerTimeline">,
): TimelineLikeItem[] | undefined {
  const list = items ?? [];
  if (list.length === 0) {
    return items as TimelineLikeItem[] | undefined;
  }
  if (plan.omitAssistantOnlyServerTimeline && serverTimelineIsAssistantTextOnly(list)) {
    return undefined;
  }
  if (plan.stripTimelineAssistantText) {
    const kept = list.filter((item) => String(item.kind ?? "").trim() !== "assistant_text");
    return kept.length > 0 ? kept : undefined;
  }
  return list as TimelineLikeItem[];
}

/**
 * Resolve a single display plan for an assistant conversation message.
 *
 * Call once before building timeline (include flags), then again after timeline
 * items are built with `builtTimelineItems` + `hasAgentMessageTimeline`.
 */
export function resolveAssistantDisplayPlan(input: {
  message: ConversationMessage;
  surface?: CodexTranscriptSurface;
  /** Server timeline items (message.timelineItems) for build options. */
  serverTimelineItems?: readonly TimelineLikeItem[];
  /** Client-built timeline items after buildAgentMessageTimelineItems. */
  builtTimelineItems?: readonly TimelineLikeItem[];
  hasAgentMessageTimeline?: boolean;
}): AssistantDisplayPlan {
  const message = input.message;
  const surface = input.surface;
  const projectedAnswer = compactText(answerProjectionContent(message));
  const turnItems = consolidateSessionTurnItemsV2(message.turnItems);
  const hasTurnItemPackage = turnItems.length > 0;
  const protocolSurface = resolveAssistantTurnRenderSurface({
    answerProjectionContent: projectedAnswer,
    thoughtContent: message.thought,
    feedbackEvents: message.feedbackEvents,
    codexTranscript: message.codexTranscript,
    turnItems: message.turnItems,
  });

  const packageOwnsFinalAnswer = (
    protocolSurface.protocol === "canonical_turn_items_v2"
    && Boolean(compactText(protocolSurface.answerContent))
  );
  const nativePrimary = surface?.mode === "native";
  const nativeOwnsFinalAnswer = surfaceNativeOwnsFinalAnswer(surface, projectedAnswer)
    || (hasTurnItemPackage && packageOwnsFinalAnswer && shouldRenderCodexTranscriptSurface(surface));

  const serverTimelineItems = input.serverTimelineItems ?? message.timelineItems ?? [];
  const serverHasAssistantText = serverTimelineItems.some(
    (item) => String(item.kind ?? "").trim() === "assistant_text",
  );

  // Phase C: package mode never injects answer via timeline.
  const includeTimelineAssistantText = hasTurnItemPackage
    ? false
    : (serverHasAssistantText && !nativeOwnsFinalAnswer);
  const stripTimelineAssistantText = hasTurnItemPackage || nativeOwnsFinalAnswer;
  const omitAssistantOnlyServerTimeline = (
    hasTurnItemPackage
    || nativeOwnsFinalAnswer
  ) && serverTimelineIsAssistantTextOnly(serverTimelineItems);

  const timelineForCover = input.builtTimelineItems ?? serverTimelineItems;
  const timelineOwnsFinalAnswer = Boolean(
    !hasTurnItemPackage
    && input.hasAgentMessageTimeline
    && timelineForCover.some((item) => String(item.kind ?? "").trim() === "assistant_text")
    && timelineAssistantTextCoversFinalAnswer(timelineForCover, projectedAnswer),
  );

  let answerOwner: AssistantAnswerOwner = "none";
  let renderMode: AssistantRenderMode = "legacy";
  if (hasTurnItemPackage) {
    renderMode = "package_cells";
    answerOwner = packageOwnsFinalAnswer
      ? "canonical_turn_items"
      : (projectedAnswer ? "response_section" : "none");
  } else if (nativeOwnsFinalAnswer) {
    renderMode = "native_transcript";
    answerOwner = "native_transcript";
  } else if (timelineOwnsFinalAnswer) {
    answerOwner = "timeline_assistant_text";
  } else if (projectedAnswer) {
    answerOwner = "response_section";
  }

  const suppressProjectedError = Boolean(surface?.suppressProjectedError);
  const suppressProjectedProcess = Boolean(surface?.suppressProjectedProcess);
  // Package/native/timeline final ownership suppresses the dedicated response body.
  const suppressProjectedResponse = suppressProjectedError
    || packageOwnsFinalAnswer
    || nativeOwnsFinalAnswer
    || timelineOwnsFinalAnswer
    // Package mode with cells: prefer single cells track even if final text still streaming empty.
    || (hasTurnItemPackage && shouldRenderCodexTranscriptSurface(surface) && !projectedAnswer);

  const shouldRenderCodexSurface = shouldRenderCodexTranscriptSurface(surface)
    || (hasTurnItemPackage && Boolean(surface?.cells?.length));

  return {
    protocol: protocolSurface.protocol,
    renderMode,
    hasTurnItemPackage,
    answerOwner,
    nativePrimary: Boolean(nativePrimary) || hasTurnItemPackage,
    nativeOwnsFinalAnswer: packageOwnsFinalAnswer || nativeOwnsFinalAnswer,
    timelineOwnsFinalAnswer,
    includeTimelineAssistantText,
    omitAssistantOnlyServerTimeline,
    stripTimelineAssistantText,
    suppressProjectedResponse,
    suppressProjectedProcess,
    suppressProjectedTurnStatus: Boolean(surface?.suppressProjectedTurnStatus),
    suppressProjectedError,
    // Codex-like: process timeline may sit *before* final answer cells when the
    // surface only owns the answer and tools live on feedback/timeline.
    // Never alongside when cells already render process (would reverse/dupe tools).
    shouldRenderNativeProcessAlongsideAnswer: (
      (packageOwnsFinalAnswer || nativeOwnsFinalAnswer)
      && Boolean(input.hasAgentMessageTimeline)
      && !suppressProjectedProcess
    ),
    shouldRenderCodexSurface: Boolean(shouldRenderCodexSurface),
  };
}
