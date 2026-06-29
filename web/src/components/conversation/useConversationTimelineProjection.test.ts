import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { projectConversationTimelineMessages } from "./useConversationTimelineProjection";

function assistantMessage(
  id: string,
  patch: Partial<ConversationMessage> = {},
): ConversationMessage {
  return {
    id,
    role: "assistant",
    content: "回答正文",
    timestamp: "2026-06-29T10:00:00Z",
    metadata: { turnId: "turn-1" },
    ...patch,
  };
}

describe("projectConversationTimelineMessages", () => {
  it("merges same-turn live overlay process into the active turn without exposing status text as answer", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "正在唤起对话 agent...\n正在绑定 Agent 实例、私人工作区、记忆根和工具工作区。",
      streaming: true,
      streamStage: "agent_prepare",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "agent_prepare",
          summary: "正在绑定 Agent",
        },
      ],
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "这是正在流式输出的回答。",
      streaming: true,
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectConversationTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0].content).toBe("这是正在流式输出的回答。");
    expect(projection.messages[0].content).not.toContain("正在唤起对话 agent");
    expect(projection.messages[0].feedbackEvents?.map((event) => event.summary)).toEqual(["正在绑定 Agent"]);
    expect(projection.rowIdentities[0].rowKey).toBe("assistant-turn:turn-1");
    expect(projection.streamingMessages.map((message) => message.id)).toEqual(["active-turn"]);
  });

  it("does not append an active layer after a committed same-turn answer already exists", () => {
    const committed = assistantMessage("committed-answer", {
      content: "最终回答已经落库。",
      metadata: { turnId: "turn-1" },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "过期的流式尾巴",
      streaming: true,
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectConversationTimelineMessages({
      timelineMessages: [committed],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages.map((message) => message.id)).toEqual(["committed-answer"]);
    expect(projection.streamingMessages).toEqual([]);
    expect(projection.rowIdentities[0].rowKey).toBe("assistant-turn:turn-1");
  });
});
