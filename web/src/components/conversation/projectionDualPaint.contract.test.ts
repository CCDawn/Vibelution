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

describe("projection dual-paint contracts", () => {  it("does not stack compact status placeholder above a codex surface", () => {
    expect(shouldRenderCompactActiveTurnPlaceholder({
      role: "assistant",
      streaming: true,
      showResponseBlock: false,
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

  it("dedupes completed + running restream of the same thought text", () => {
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
    expect(deduped.map((cell) => cell.id)).toEqual(["run"]);
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
    expect(display.map((cell) => cell.id)).toEqual(["thought-b", "tool-b"]);
  });
});
