import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

import type { ConversationMessage } from "../../api/types";
import { projectAgentMessageTimelineMessages } from "./useConversationTimelineProjection";

const projectionSource = readFileSync(new URL("./useConversationTimelineProjection.ts", import.meta.url), "utf8");

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

describe("projectAgentMessageTimelineMessages", () => {
  it("exports the projection contract through AgentMessage timeline naming only", () => {
    expect(projectionSource).toContain("export type AgentMessageTimelineProjectionInput");
    expect(projectionSource).toContain("export type AgentMessageTimelineProjection =");
    expect(projectionSource).toContain("export function projectAgentMessageTimelineMessages");
    expect(projectionSource).not.toContain("ConversationTimelineProjectionInput");
    expect(projectionSource).not.toContain("ConversationTimelineProjection =");
    expect(projectionSource).not.toContain("projectConversationTimelineMessages");
  });

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

    const projection = projectAgentMessageTimelineMessages({
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

  it("keeps arbitrary same-turn live overlay content out of the active answer", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "过程提示：已经准备好上下文，正在等待模型响应。",
      streaming: true,
      streamStage: "model_request",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在等待模型响应",
        },
      ],
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "这是用户应该看到的回答。",
      streaming: true,
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0].content).toBe("这是用户应该看到的回答。");
    expect(projection.messages[0].content).not.toContain("过程提示");
    expect(projection.messages[0].feedbackEvents?.map((event) => event.summary)).toEqual(["正在等待模型响应"]);
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

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [committed],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages.map((message) => message.id)).toEqual(["committed-answer"]);
    expect(projection.streamingMessages).toEqual([]);
    expect(projection.rowIdentities[0].rowKey).toBe("assistant-turn:turn-1");
  });
});
