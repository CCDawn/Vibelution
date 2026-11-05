import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { resolveCodexTranscriptSurface } from "./codexNativeTranscriptSurface";
import { codexTranscriptToolRawName } from "./conversationToolActivityModel";
import { conversationToolCategoryForCell } from "./conversationToolCategory";
import { conversationToolActivityRendererForCell } from "./conversationToolActivityPresentation";

describe("codexNativeTranscriptSurface canonical projection", () => {
  it("keeps canonical assistant identity and action semantics through the native projection", () => {
    const message: ConversationMessage = {
      id: "assistant-actions", role: "assistant", timestamp: "2026-11-05T00:00:00Z", status: "completed", turnId: "actions",
      turnItems: ["source_read", "source_search", "dispatch"].map((action, index) => ({
        id: `call-${index}:1`, itemId: `call-${index}`, version: 3, sessionId: "s", turnId: "actions",
        type: "tool_call", callId: `call-${index}`, toolName: "personal_assistant_action_tool", status: "completed",
        revision: 1, sequence: index, input: JSON.stringify({ action, path: "README.md" }), output: "已完成。",
      })),
    };
    const cells = resolveCodexTranscriptSurface(message).cells;
    expect(cells.map(codexTranscriptToolRawName)).toEqual(Array(3).fill("personal_assistant_action_tool"));
    expect(cells.map((cell) => cell.title)).toEqual(["读取源码", "搜索源码", "派遣只读任务"]);
    expect(cells.map(conversationToolCategoryForCell)).toEqual(["explore", "explore", "agent"]);
    expect(cells.map((cell) => conversationToolActivityRendererForCell(cell, "zh").family)).toEqual(["files", "search", "conversation"]);
  });

  it("derives ordered tool and answer cells from turnItems", () => {
    const message: ConversationMessage = {
      id: "message-1",
      role: "assistant",
      timestamp: "2026-08-09T00:00:00Z",
      turnId: "turn-1",
      status: "completed",
      turnItems: [
        {
          id: "tool-1-r1", itemId: "tool-1", version: 3, sessionId: "session-1", turnId: "turn-1",
          type: "tool_call", callId: "call-1", toolName: "shell", status: "completed", revision: 1, sequence: 1,
          input: "pwd", output: "C:/workspace",
        },
        {
          id: "answer-1-r1", itemId: "answer-1", version: 3, sessionId: "session-1", turnId: "turn-1",
          type: "agent_message", phase: "final_answer", text: "完成。", status: "completed", revision: 1, sequence: 2,
        },
      ],
    };

    const surface = resolveCodexTranscriptSurface(message);
    expect(surface.source).toBe("turnItems");
    expect(surface.cells.map((cell) => cell.kind)).toEqual(["tool_call", "assistant_markdown"]);
    expect(surface.suppressProjectedResponse).toBe(true);
  });
});
