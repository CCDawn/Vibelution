import { describe, expect, it } from "vitest";

import type { AgentMessage } from "../../agent-thread";
import { buildAgentMessageRenderState } from "./agentMessageRenderState";

describe("agentMessageRenderState canonical parts", () => {
  it("keeps answer and tool sections on one assistant message", () => {
    const message: AgentMessage = {
      id: "message-1",
      role: "assistant",
      createdAt: "2026-08-09T00:00:00Z",
      streaming: false,
      turnId: "turn-1",
      source: { kind: "conversation-message", id: "message-1" },
      parts: [
        { id: "answer-1", type: "text", channel: "answer", text: "完成。" },
        { id: "tool-1", type: "tool-call", name: "shell", status: "completed", summary: "ok" },
      ],
    };

    const state = buildAgentMessageRenderState(message);
    expect(state.sectionState.hasResponseBlock).toBe(true);
    expect(state.sectionState.hasProcessSection).toBe(true);
    expect(state.toolCalls.map((tool) => tool.name)).toEqual(["shell"]);
  });
});
