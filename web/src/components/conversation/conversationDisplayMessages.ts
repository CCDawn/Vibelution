import type { ConversationMessage } from "../../api/types";
import { projectConversationDisplayPipeline } from "./conversationDisplayPipeline";
import { recordConversationDisplayFrame } from "./conversationDisplayTelemetry";

/**
 * Display projection entry point.
 *
 * Selection now lives in one place (`projectConversationDisplayPipeline`) so
 * the show/hide rules cannot drift apart again. This wrapper keeps the
 * historical export name and records one bounded telemetry frame per call, so a
 * repeated-projection report can be answered with "which stage dropped or
 * folded this row" instead of another manual bisect across five filters.
 */
export function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  const startedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
  const result = projectConversationDisplayPipeline(messages);
  const finishedAt = typeof performance !== "undefined" ? performance.now() : Date.now();
  recordConversationDisplayFrame(result, {
    durationMs: finishedAt - startedAt,
    inputCount: messages.length,
    // This entry point re-projects the whole list, so it is a full rebuild by
    // definition. The P3 counter uses this to show the pre-optimisation baseline.
    rebuiltMessages: messages.length,
  });
  return result.messages;
}

/**
 * Same projection with the stage trace and per-row discard reasons attached.
 * Intended for diagnostics and tests, not for the render hot path.
 */
export function inspectConversationDisplayMessages(messages: ConversationMessage[]) {
  return projectConversationDisplayPipeline(messages);
}
