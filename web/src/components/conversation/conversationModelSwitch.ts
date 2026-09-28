/**
 * Model-switch boundary computation for the conversation timeline (「模型切换
 * 分隔线」pure logic). Walks settled session messages, groups them into turns
 * (a turn starts at every user message), and marks the user message that opens
 * each turn whose assistant model differs from the previous turn-with-model.
 *
 * Deliberately label-free: no display strings, no i18n, no DOM. The rendering
 * layer owns how a boundary is presented.
 */

export type ConversationModelSwitchBoundary =
  | { kind: "initial"; toModelId: string }
  | { kind: "switch"; fromModelId: string; toModelId: string };

/**
 * Minimal structural view of a settled session message. `ConversationMessage`
 * from `../../api/types` satisfies it, so callers pass the timeline array
 * straight through without coupling this module to the full union.
 */
export type ConversationModelSwitchMessage = {
  id: string;
  role: string;
  metadata?: Record<string, unknown>;
};

/**
 * The assistant model that produced one message, or "" when the message did
 * not carry a provider-reported model id. Reads `metadata.llmUsage.llmModelId`
 * defensively: the backend stamps usage only on settled assistant turns
 * (core/web/services/session/persist.py), and metadata is an untyped record.
 */
export function conversationMessageLlmModelId(
  message: Pick<ConversationModelSwitchMessage, "metadata">,
): string {
  const usage = message.metadata?.llmUsage;
  if (!usage || typeof usage !== "object") {
    return "";
  }
  const modelId = (usage as Record<string, unknown>).llmModelId;
  return typeof modelId === "string" ? modelId.trim() : "";
}

/**
 * Maps the id of the USER message that opens a turn to that turn's model
 * boundary. Compression markers (assistant-role rows with
 * `metadata.kind === "context_compression_marker"`) carry no llmUsage, so they
 * are neither a model source nor a turn boundary; turns without an assistant
 * model are skipped entirely. The first turn-with-model yields `initial`;
 * every later model change yields `switch` relative to the previous
 * turn-with-model (unchanged models attach nothing).
 */
export function buildConversationModelSwitchBoundaries(
  messages: readonly ConversationModelSwitchMessage[],
): ReadonlyMap<string, ConversationModelSwitchBoundary> {
  const boundaries = new Map<string, ConversationModelSwitchBoundary>();
  let currentUserMessageId: string | null = null;
  let previousModelId = "";
  for (const message of messages) {
    if (message.role === "user") {
      currentUserMessageId = message.id;
      continue;
    }
    if (message.role !== "assistant") {
      continue;
    }
    const modelId = conversationMessageLlmModelId(message);
    if (!modelId || currentUserMessageId === null) {
      // No model (compression marker, tool-only turn) or no preceding user
      // row (assistant-anchored transcript head): neither advances the
      // previous-model chain nor opens a boundary.
      continue;
    }
    if (!previousModelId) {
      boundaries.set(currentUserMessageId, { kind: "initial", toModelId: modelId });
    } else if (modelId !== previousModelId) {
      boundaries.set(currentUserMessageId, {
        kind: "switch",
        fromModelId: previousModelId,
        toModelId: modelId,
      });
    }
    previousModelId = modelId;
    // One boundary per turn: later assistant rows of the same turn must not
    // re-attach to the user message.
    currentUserMessageId = null;
  }
  return boundaries;
}
