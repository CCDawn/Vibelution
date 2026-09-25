import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { resolveAssistantDisplayPlan } from "./assistantDisplayPlan";
import {
  hasNativeProcessCells,
  resolveCodexTranscriptSurface,
} from "./codexNativeTranscriptSurface";
import {
  dedupeCodexTranscriptCellsForDisplay,
  dedupeThoughtLikeTranscriptCells,
} from "./codexTranscriptCells";
import { shouldRenderCompactActiveTurnPlaceholder } from "./conversationOperationPresentation";

function message(patch: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message-1",
    role: "assistant",
    content: "",
    timestamp: "2026-08-08T03:00:00Z",
    ...patch,
  };
}

describe("projection dual-paint contracts", () => {
  // Defect 7b (2026-09-26): the old "never stack the placeholder above a codex
  // surface" rule retired the shell on the first streamed answer cell — one
  // frame before the backend's responding status row — so the responding
  // stage could never render. The shell now coexists with the codex answer
  // while the turn streams and retires only at settle; running tools and
  // errors still suppress it (see shouldRenderCompactActiveTurnPlaceholder).
  it("keeps the compact status placeholder beside the codex answer while streaming", () => {
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: true,
    })).toBe(true);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: false,
      showResponseBlock: true,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: true,
    })).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: false,
    })).toBe(true);
  });

  it("optimistic pending + empty turnItems: compact placeholder on, suppress off", () => {
    const optimistic = message({
      status: "pending",
      turnItems: [],
      metadata: { processStage: "user_submit" },
    });
    const plan = resolveAssistantDisplayPlan({ message: optimistic });
    expect(plan.suppressProjectedResponse).toBe(false);
    expect(plan.suppressProjectedTurnStatus).toBe(false);
    expect(plan.hasTurnItemPackage).toBe(false);
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: false,
      turnErrorMessage: false,
      hasCodexSurface: Boolean(plan.shouldRenderCodexSurface),
    })).toBe(true);
  });

  it("inFlight + hasActiveProcess does not force compact (no force-OR)", () => {
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: false,
      inFlight: true,
      showResponseBlock: false,
      hasFeedbackTimeline: false,
      hasActiveProcess: true,
      turnErrorMessage: false,
      hasCodexSurface: false,
    })).toBe(false);
  });

  it("prefers the user-facing commentary copy over its reasoning restream", () => {
    const deduped = dedupeThoughtLikeTranscriptCells([
      {
        id: "done",
        kind: "assistant_markdown",
        messageId: "m",
        status: "completed",
        tone: "neutral",
        phase: "commentary",
        text: "短思考",
      },
      {
        id: "run",
        kind: "reasoning_summary",
        messageId: "m",
        status: "running",
        tone: "running",
        text: "短思考，继续展开。",
      },
    ]);
    expect(deduped.map((cell) => cell.id)).toEqual(["done"]);
  });

  it("display dedupe collapses duplicate tool identities after thought dedupe", () => {
    const display = dedupeCodexTranscriptCellsForDisplay([
      {
        id: "thought-a",
        kind: "assistant_markdown",
        messageId: "m",
        status: "completed",
        tone: "neutral",
        phase: "commentary",
        text: "先看状态",
      },
      {
        id: "thought-b",
        kind: "reasoning_summary",
        messageId: "m",
        status: "running",
        tone: "running",
        text: "先看状态，再决定下一步",
      },
      {
        id: "tool-a",
        kind: "tool_call",
        messageId: "m",
        status: "running",
        tone: "running",
        title: "cli_tool",
        sourceItemId: "src-1",
        toolLifecycleModel: {
          toolCalls: [{
            toolCallId: "call-x",
            rawOperationId: "op-x",
            status: "running",
            title: "cli_tool",
            rawToolName: "cli_tool",
            runtimeKind: "terminal",
          }],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
      {
        id: "tool-b",
        kind: "tool_call",
        messageId: "m",
        status: "completed",
        tone: "neutral",
        title: "cli_tool",
        sourceItemId: "src-1",
        toolLifecycleModel: {
          toolCalls: [{
            toolCallId: "call-x",
            rawOperationId: "op-x",
            status: "completed",
            title: "cli_tool",
            rawToolName: "cli_tool",
            runtimeKind: "terminal",
          }],
          terminalOperations: [],
          terminalSessions: [],
          modelObservations: [],
        },
      },
    ]);
    expect(display.map((cell) => cell.id)).toEqual(["thought-a", "tool-b"]);
  });
});
