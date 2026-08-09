/**
 * Display ownership for one canonical assistant turn.
 *
 * ConversationMessage carries no parallel content, timeline or transcript
 * fields.  The local Codex surface is derived exclusively from turnItems.
 */
import type { ConversationMessage } from "../../api/types";
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

/** Resolve the one rendering track for an assistant ConversationMessage. */
export function resolveAssistantDisplayPlan(input: {
  message: ConversationMessage;
  surface?: CodexTranscriptSurface;
}): AssistantDisplayPlan {
  const turnItems = input.message.role === "assistant"
    ? consolidateSessionTurnItemsV2(input.message.turnItems)
    : [];
  const protocolSurface = resolveAssistantTurnRenderSurface({ turnItems });
  const hasTurnItemPackage = turnItems.length > 0;
  const surface = input.surface;
  const hasCells = Boolean(surface?.cells?.length);
  const surfaceOwnsProcess = Boolean(surface?.suppressProjectedProcess)
    || (surface?.mode === "native" && hasNativeProcessCells(surface.cells ?? []));
  const suppressProjectedError = Boolean(surface?.suppressProjectedError);

  return {
    protocol: protocolSurface.protocol,
    renderMode: hasTurnItemPackage ? "turn_items" : "empty",
    hasTurnItemPackage,
    answerOwner: hasTurnItemPackage ? "canonical_turn_items" : "none",
    nativePrimary: hasTurnItemPackage,
    // The cells are a pure local rendering projection of this same item list.
    suppressProjectedResponse: hasTurnItemPackage || suppressProjectedError,
    suppressProjectedProcess: surfaceOwnsProcess,
    suppressProjectedTurnStatus: hasTurnItemPackage || suppressProjectedError,
    suppressProjectedError,
    shouldRenderCodexSurface: hasCells && shouldRenderCodexTranscriptSurface(surface),
  };
}
