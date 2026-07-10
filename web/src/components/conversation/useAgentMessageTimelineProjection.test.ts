import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";

import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import { buildAgentMessageOperations } from "./agentMessageOperations";
import { buildAgentMessageTimelineItems } from "./agentMessageTimeline";
import { projectAgentMessageTimelineMessages } from "./useAgentMessageTimelineProjection";

const projectionSource = readFileSync(new URL("./useAgentMessageTimelineProjection.ts", import.meta.url), "utf8");

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
  it("keeps active-turn projection on an AgentMessage-named hook module", () => {
    expect(existsSync(new URL("./useAgentMessageTimelineProjection.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./useConversationTimelineProjection.ts", import.meta.url))).toBe(false);
  });

  it("exports the projection contract through AgentMessage timeline naming only", () => {
    expect(projectionSource).toContain("export type AgentMessageTimelineProjectionInput");
    expect(projectionSource).toContain("export type AgentMessageTimelineProjection =");
    expect(projectionSource).toContain("export function projectAgentMessageTimelineMessages");
    expect(projectionSource).toContain("./conversationMessageIdentity");
    expect(projectionSource).not.toContain("function metadataText");
    expect(projectionSource).not.toContain("function conversationMessageTurnId");
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
    expect(projection.messages[0].feedbackEvents).toBeUndefined();
    expect(projection.agentMessages.map((message) => message.id)).toEqual(["active-turn"]);
    expect(projection.agentMessages[0].parts.map((part) => part.type)).toEqual(["text"]);
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
    expect(projection.messages[0].feedbackEvents).toBeUndefined();
  });

  it("keeps a compact active turn visible when the run only has internal status so far", () => {
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
      content: "",
      streaming: true,
      streamStage: "model_request",
      feedbackEvents: [
        {
          sequence: 2,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型，等待首个响应片段。",
        },
      ],
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0]).toMatchObject({
      id: "active-turn",
      role: "assistant",
      streaming: true,
      content: "",
      metadata: expect.objectContaining({
        kind: "session_active_turn_layer",
        turnId: "turn-1",
      }),
    });
    expect(projection.messages[0].feedbackEvents).toBeUndefined();
    expect(projection.agentMessages.map((message) => message.id)).toEqual(["active-turn"]);
    expect(projection.streamingMessages.map((message) => message.id)).toEqual(["active-turn"]);
    expect(projection.rowIdentities[0].rowKey).toBe("assistant-turn:turn-1");
  });

  it("drops a stale live overlay after a committed same-turn answer arrives", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "你好！我在。需要我帮你做什么？",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "read_file_tool",
          summary: "保留 overlay 独有过程数据",
        },
      ],
      timelineItems: [
        {
          id: "live-answer-text",
          kind: "assistant_text",
          status: "completed",
          text: "你好！我在。需要我帮你做什么？",
        },
        {
          id: "overlay-operation",
          kind: "operation",
          status: "completed",
          title: "读取文件",
          summary: "保留 overlay 独有过程数据",
          operationIds: ["read-file-operation"],
        },
      ],
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "live-overlay",
        cells: [
          {
            id: "overlay-tool-cell",
            kind: "tool_call",
            messageId: "live-overlay",
            status: "completed",
            tone: "neutral",
            title: "read_file_tool",
            summary: "保留 overlay 原生工具过程",
          },
        ],
        toolCalls: [],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
      metadata: { kind: "session_live_overlay", turnId: "live:turn-duplicate" },
    });
    const committed = assistantMessage("committed-answer", {
      content: "你好！我在。需要我帮你做什么？",
      streaming: false,
      timelineItems: [
        {
          id: "committed-answer-text",
          kind: "assistant_text",
          status: "completed",
          text: "你好！我在。需要我帮你做什么？",
        },
      ],
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "committed-answer",
        cells: [
          {
            id: "committed-answer-cell",
            kind: "assistant_markdown",
            messageId: "committed-answer",
            status: "completed",
            tone: "neutral",
            text: "你好！我在。需要我帮你做什么？",
          },
        ],
        toolCalls: [],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
      metadata: { turnId: "turn-duplicate" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay, committed],
    });

    expect(projection.messages.map((message) => message.id)).toEqual(["committed-answer"]);
    expect(projection.agentMessages.map((message) => message.id)).toEqual(["committed-answer"]);
    expect(projection.messages[0].timelineItems?.map((item) => item.id)).toEqual([
      "overlay-operation",
      "committed-answer-text",
    ]);
    expect(projection.messages[0].feedbackEvents?.map((event) => event.summary)).toEqual([
      "保留 overlay 独有过程数据",
    ]);
    expect(projection.messages[0].codexTranscript?.messageId).toBe("committed-answer");
    expect(projection.messages[0].codexTranscript?.cells.map((cell) => cell.id)).toEqual([
      "overlay-tool-cell",
      "committed-answer-cell",
    ]);
    expect(projection.rowIdentities).toHaveLength(1);
  });

  it("keeps a live overlay visible while no committed same-turn answer exists", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "尚未完成的回答",
      streaming: true,
      metadata: { kind: "session_live_overlay", turnId: "live:turn-interrupted" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
    });

    expect(projection.messages.map((message) => message.id)).toEqual(["live-overlay"]);
    expect(projection.streamingMessages.map((message) => message.id)).toEqual(["live-overlay"]);
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

  it("normalizes timeline messages to chronological order before projecting rows", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        assistantMessage("assistant-new", {
          content: "new answer",
          timestamp: "2026-07-09T01:27:00Z",
          metadata: { turnId: "turn-2" },
        }),
        assistantMessage("assistant-old", {
          content: "old answer",
          timestamp: "2026-07-09T01:26:48Z",
          metadata: { turnId: "turn-1" },
        }),
      ],
    });

    expect(projection.messages.map((message) => message.id)).toEqual([
      "assistant-old",
      "assistant-new",
    ]);
    expect(projection.agentMessages.map((message) => message.id)).toEqual([
      "assistant-old",
      "assistant-new",
    ]);
  });

  it("drops process-only legacy DTO fields when no protocol event exists", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        assistantMessage("legacy-process-only", {
          content: "",
          thought: "legacy thought should not reserve a row",
          toolCalls: [{ name: "legacy_tool", status: "done", summary: "legacy tool" }],
          mentalSnapshot: {
            mood: "",
            feeling: "",
            whisper: "",
            summary: "legacy mental",
            cognitiveState: "normal",
            confidence: 0,
            sampleSize: 0,
            interventionCount: 0,
            updatedAt: "2026-07-09T01:00:00Z",
            source: "test",
          },
        }),
      ],
    });

    expect(projection.messages).toEqual([]);
    expect(projection.agentMessages).toEqual([]);
    expect(projection.rowIdentities).toEqual([]);
  });

  it("coalesces same-turn live overlay feedback events by semantic identity", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "正在读取文件",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          name: "read_file_tool",
          status: "running",
          summary: "正在读取 ConversationView.tsx",
          resultPreview: "opening...",
        },
      ],
      timelineItems: [
        {
          id: "tool-read-1",
          kind: "operation",
          status: "running",
          title: "读取",
          summary: "正在读取 ConversationView.tsx",
          operationIds: ["tool-read-operation"],
        },
      ],
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "回答正文",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          name: "read_file_tool",
          status: "done",
          summary: "已读取 ConversationView.tsx",
          resultPreview: "loaded",
        },
      ],
      timelineItems: [
        {
          id: "tool-read-1",
          kind: "operation",
          status: "completed",
          title: "读取",
          summary: "已读取 ConversationView.tsx",
          operationIds: ["tool-read-operation"],
        },
      ],
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0].toolCalls).toBeUndefined();
    expect(projection.messages[0].feedbackEvents).toEqual([
      {
        sequence: 1,
        kind: "tool",
        name: "read_file_tool",
        status: "done",
        summary: "已读取 ConversationView.tsx",
        resultPreview: "loaded",
      },
    ]);
    expect(projection.messages[0].timelineItems).toEqual([
      {
        id: "tool-read-1",
        kind: "operation",
        status: "completed",
        title: "读取",
        summary: "已读取 ConversationView.tsx",
        operationIds: ["tool-read-operation"],
      },
    ]);
  });

  it("keeps live overlay ids as aliases so command groups can resolve active feedback operations", () => {
    const liveOverlay = assistantMessage("session-1-message-live-turn-1", {
      content: "正在运行命令",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 6,
          kind: "tool",
          status: "running",
          name: "cli_tool",
          summary: "git branch --show-current",
        },
        {
          sequence: 7,
          kind: "tool",
          status: "running",
          name: "cli_tool",
          summary: "git status --short --branch",
        },
      ],
      timelineItems: [
        {
          id: "session-1-message-live-turn-1-timeline-command-group-6-7",
          kind: "command_group",
          status: "running",
          title: "正在运行 2 条命令",
          summary: "git branch --show-current；git status --short --branch",
          operationIds: [
            "session-1-message-live-turn-1-feedback-6",
            "session-1-message-live-turn-1-feedback-7",
          ],
        },
      ],
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeTurn = assistantMessage("session-1-message-active-turn-1", {
      content: "回答正文",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 6,
          kind: "tool",
          status: "done",
          name: "cli_tool",
          summary: "main",
        },
        {
          sequence: 7,
          kind: "tool",
          status: "done",
          name: "cli_tool",
          summary: "## main...origin/main [ahead 858]",
        },
      ],
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });
    const projectedMessage = projection.messages[0];
    const agentMessage = conversationMessageToAgentMessage(projectedMessage);
    const operations = buildAgentMessageOperations(agentMessage, {
      thought: "思考",
      mental: "心智状态",
      status: "运行状态",
    });
    const timelineItems = buildAgentMessageTimelineItems(
      agentMessage,
      operations,
      { lang: "zh" },
      projectedMessage.timelineItems,
    );

    expect(projectedMessage.metadata?.projectedMessageIds).toEqual([
      "session-1-message-live-turn-1",
      "session-1-message-active-turn-1",
    ]);
    expect(timelineItems.map((item) => item.kind)).toEqual(["command_group"]);
    expect(timelineItems[0]).toMatchObject({
      kind: "command_group",
      title: "正在运行 2 条命令",
    });
    expect(timelineItems).not.toContainEqual(expect.objectContaining({
      kind: "operation",
      title: "工具调用投影缺失",
    }));
  });

  it("keeps same-name live overlay feedback tools separate when their stable inputs differ", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "正在读取文件",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 0,
          kind: "tool",
          name: "read_file_tool",
          status: "done",
          summary: "读取 A",
          arguments: { path: "A.ts" },
        },
      ],
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "回答正文",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 0,
          kind: "tool",
          name: "read_file_tool",
          status: "done",
          summary: "读取 B",
          arguments: { path: "B.ts" },
        },
      ],
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [liveOverlay],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages[0].toolCalls).toBeUndefined();
    expect(projection.messages[0].feedbackEvents?.map((event) => event.summary)).toEqual([
      "读取 A",
      "读取 B",
    ]);
  });
});
