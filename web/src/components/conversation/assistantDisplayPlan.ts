/**
 * Display ownership for one canonical assistant turn.
 *
 * ConversationMessage carries no parallel content, timeline or transcript
 * fields.  The local Codex surface is derived exclusively from turnItems.
 *
 * Ownership / suppress gates require *visible paint* (displayable surface cells),
 * not merely a non-empty turnItems array. Status-only or empty shells must not
 * suppress the Thinking/waiting placeholder while a turn is in flight.
 */
import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import {
  consolidateSessionTurnItemsV2,
  resolveAssistantTurnRenderSurface,
  type ChatTurnRenderProtocol,
} from "../../routes/chatTurnProtocol";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import { hasNativeProcessCells } from "./codexNativeTranscriptSurface";
import { shouldRenderCodexTranscriptSurface } from "./conversationOperationPresentation";

export type AssistantAnswerOwner = "canonical_turn_items" | "none";
export type AssistantRenderMode = "turn_items" | "empty";

export type AssistantDisplayPlan = {
  protocol: ChatTurnRenderProtocol;
  renderMode: AssistantRenderMode;
  hasTurnItemPackage: boolean;
  answerOwner: AssistantAnswerOwner;
  nativePrimary: boolean;
  suppressProjectedResponse: boolean;
  suppressProjectedProcess: boolean;
  suppressProjectedTurnStatus: boolean;
  suppressProjectedError: boolean;
  shouldRenderCodexSurface: boolean;
};

function compactText(value: unknown) {
  return String(value ?? "").trim();
}

/** True when turnItems already carry displayable agent answer text (tests may omit surface). */
export function hasCanonicalAnswerItems(turnItems: readonly SessionTurnItem[]): boolean {
  return turnItems.some((item) => (
    item.type === "agent_message" && Boolean(compactText(item.text))
  ));
}

/** Visible paint: native surface cells, or canonical answer items (even with empty surface). */
export function hasAssistantVisiblePaint(input: {
  turnItems: readonly SessionTurnItem[];
  surface?: CodexTranscriptSurface;
}): boolean {
  if (shouldRenderCodexTranscriptSurface(input.surface)) {
    return true;
  }
  if (hasCanonicalAnswerItems(input.turnItems)) {
    return true;
  }
  return false;
}

/** Resolve the one rendering track for an assistant ConversationMessage. */
export function resolveAssistantDisplayPlan(input: {
  message: ConversationMessage;
  surface?: CodexTranscriptSurface;
}): AssistantDisplayPlan {
  const turnItems = input.message.role === "assistant"
    ? consolidateSessionTurnItemsV2(input.message.turnItems)
    : [];
  const protocolSurface = resolveAssistantTurnRenderSurface({ turnItems });
  const surface = input.surface;
  const hasVisiblePaint = hasAssistantVisiblePaint({ turnItems, surface });
  // Package ownership = visible paint only (status-only / empty shells are not a package).
  const hasTurnItemPackage = hasVisiblePaint;
  const surfaceOwnsProcess = Boolean(surface?.suppressProjectedProcess)
    || (surface?.mode === "native" && hasNativeProcessCells(surface.cells ?? []));
  const suppressProjectedError = Boolean(surface?.suppressProjectedError);

  return {
    protocol: protocolSurface.protocol,
    renderMode: hasTurnItemPackage ? "turn_items" : "empty",
    hasTurnItemPackage,
    answerOwner: hasTurnItemPackage ? "canonical_turn_items" : "none",
    nativePrimary: hasTurnItemPackage,
    // Suppress projected rails only when there is visible paint (or surface error ownership).
    // In-flight empty / status-only turnItems leave suppress false so the placeholder can render.
    suppressProjectedResponse: hasVisiblePaint || suppressProjectedError,
    suppressProjectedProcess: surfaceOwnsProcess,
    suppressProjectedTurnStatus: hasVisiblePaint || suppressProjectedError,
    suppressProjectedError,
    shouldRenderCodexSurface: shouldRenderCodexTranscriptSurface(surface),
  };
}
