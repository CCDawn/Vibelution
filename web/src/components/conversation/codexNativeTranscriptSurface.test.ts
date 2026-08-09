import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { resolveCodexTranscriptSurface } from "./codexNativeTranscriptSurface";

describe("codexNativeTranscriptSurface canonical projection", () => {
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
