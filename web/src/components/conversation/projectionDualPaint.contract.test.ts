import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { resolveAssistantDisplayPlan } from "./assistantDisplayPlan";
import {
  hasNativeProcessCells,
  resolveCodexTranscriptSurface,
} from "./codexNativeTranscriptSurface";
import { dedupeThoughtLikeTranscriptCells } from "./codexTranscriptCells";
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
  it("suppresses outer process when native commentary owns the trail (no second thought rail)", () => {
    const msg = message({
      thought: "legacy feedback thought copy",
      feedbackEvents: [
        { sequence: 1, kind: "thought", status: "running", summary: "legacy feedback thought copy" },
      ],
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "c1",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "running",
            tone: "running",
            phase: "commentary",
            channel: "commentary",
            text: "我先了解一下当前工作区状态。",
          },
        ],
      },
    });
    const surface = resolveCodexTranscriptSurface(msg);
    expect(hasNativeProcessCells(surface.cells)).toBe(true);
    expect(surface.suppressProjectedProcess).toBe(true);
    const plan = resolveAssistantDisplayPlan({ message: msg, surface });
    expect(plan.suppressProjectedProcess).toBe(true);
    expect(plan.shouldRenderCodexSurface).toBe(true);
    // Outer processNode is gated by suppressProjectedProcess — must stay true.
  });

  it("suppresses outer process when native tools are present even if feedback also has tools", () => {
    const msg = message({
      feedbackEvents: [
        { sequence: 1, kind: "tool", status: "done", name: "grep_search_tool", summary: "ok" },
      ],
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "message-1",
        cells: [
          {
            id: "t1",
            kind: "tool_call",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            title: "grep_search_tool",
            summary: "ok",
          },
          {
            id: "a1",
            kind: "assistant_markdown",
            messageId: "message-1",
            status: "completed",
            tone: "neutral",
            phase: "final_answer",
            terminal: true,
            text: "检查完成。",
          },
        ],
      },
    });
    const surface = resolveCodexTranscriptSurface(msg);
    const plan = resolveAssistantDisplayPlan({ message: msg, surface });
    expect(plan.suppressProjectedProcess).toBe(true);
    expect(plan.suppressProjectedResponse).toBe(true);
    expect(plan.shouldRenderNativeProcessAlongsideAnswer).toBe(false);
  });

  it("does not stack compact status placeholder above a codex surface", () => {
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
});
