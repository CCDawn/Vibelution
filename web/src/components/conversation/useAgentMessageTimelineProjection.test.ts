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

  it("keeps the active same-turn layer after non-terminal commentary", () => {
    const commentary = assistantMessage("assistant-commentary", {
      content: "I will inspect the file.",
      streaming: false,
      metadata: { kind: "journal_assistant_partial", turnId: "turn-1" },
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: "assistant-commentary",
        cells: [{
          id: "commentary-cell",
          kind: "assistant_markdown",
          messageId: "assistant-commentary",
          status: "running",
          tone: "running",
          channel: "commentary",
          phase: "commentary",
          text: "I will inspect the file.",
        }],
      },
    });
    const activeTurn = assistantMessage("active-turn", {
      content: "The version is 1.2.3.",
      streaming: true,
      feedbackEvents: [{
        sequence: 1,
        kind: "tool",
        callId: "call-read-version",
        status: "done",
        name: "read_file_tool",
        summary: "VERSION -> 1.2.3",
      }],
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [commentary],
      activeTurnMessage: activeTurn,
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0].metadata?.projectedMessageIds).toEqual([
      "assistant-commentary",
      "active-turn",
    ]);
    expect(projection.messages[0].content).toContain("I will inspect the file.");
    expect(projection.messages[0].content).toContain("The version is 1.2.3.");
    expect(projection.messages[0].feedbackEvents).toEqual([
      expect.objectContaining({
        callId: "call-read-version",
        status: "done",
      }),
    ]);
  });

  it("keeps identical assistant text from distinct turns as distinct rows", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        assistantMessage("assistant-turn-a", { content: "确认。", metadata: { turnId: "turn-a" } }),
        assistantMessage("assistant-turn-b", { content: "确认。", metadata: { turnId: "turn-b" } }),
      ],
    });

    expect(projection.messages.map((message) => message.id)).toEqual([
      "assistant-turn-a",
      "assistant-turn-b",
    ]);
    expect(projection.rowIdentities.map((row) => row.rowKey)).toEqual([
      "assistant-turn:turn-a",
      "assistant-turn:turn-b",
    ]);
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

  it("collapses repeated persisted copies of the same turn across history windows", () => {
    const userMessage = (id: string): ConversationMessage => ({
      id,
      role: "user",
      content: "继续前端开发",
      timestamp: "2026-05-18T11:55:00Z",
      metadata: { kind: "journal_user_message", turnId: "turn-user" },
    });
    const persistedAssistant = (id: string, cellId: string): ConversationMessage => assistantMessage(id, {
      content: "已经接到真实状态了。",
      timestamp: "2026-05-18T11:56:00Z",
      toolCalls: [
        { name: "read_file_tool", status: "done" },
        { name: "search_code_tool", status: "done" },
      ],
      codexTranscript: {
        version: 1,
        source: "native",
        messageId: id,
        cells: [
          {
            id: cellId,
            kind: "tool_call",
            messageId: id,
            status: "completed",
            tone: "neutral",
            title: "read_file_tool",
          },
        ],
        toolCalls: [],
        terminalOperations: [],
        terminalSessions: [],
        modelObservations: [],
      },
      metadata: { kind: "journal_assistant_message", turnId: "turn-assistant" },
    });

    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        userMessage("user-first"),
        persistedAssistant("assistant-first", "tool-cell-first"),
        userMessage("user-repeated"),
        persistedAssistant("assistant-repeated", "tool-cell-repeated"),
      ],
    });

    expect(projection.messages.map((message) => message.id)).toEqual([
      "user-first",
      "assistant-first",
    ]);
    expect(projection.messages[0].metadata?.projectedMessageIds).toEqual([
      "user-first",
      "user-repeated",
    ]);
    expect(projection.messages[1].metadata?.projectedMessageIds).toEqual([
      "assistant-first",
      "assistant-repeated",
    ]);
    expect(projection.messages[1].codexTranscript?.cells.map((cell) => cell.title)).toEqual([
      "read_file_tool",
    ]);
  });

  it("lets the canonical terminal error own failure status for its turn", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [
        assistantMessage("assistant-partial", {
          content: "你好，我在。",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "done",
              name: "model_request",
              summary: "模型请求完成",
            },
            {
              sequence: 2,
              kind: "status",
              status: "failed",
              name: "failed",
              summary: "模型请求失败",
            },
          ],
          metadata: { kind: "journal_assistant_message", turnId: "turn-error" },
        }),
        assistantMessage("terminal-error", {
          content: "模型服务上游暂时失败，本轮没有完成。",
          feedbackEvents: undefined,
          codexTranscript: {
            version: 1,
            source: "native",
            messageId: "terminal-error",
            cells: [
              {
                id: "terminal-error-cell",
                kind: "error_notice",
                messageId: "terminal-error",
                status: "failed",
                tone: "error",
                text: "模型服务上游暂时失败，本轮没有完成。",
              },
            ],
            toolCalls: [],
            terminalOperations: [],
            terminalSessions: [],
            modelObservations: [],
          },
          metadata: { kind: "turn_error", turnId: "turn-error", providerFailure: true },
        }),
      ],
    });

    expect(projection.messages.map((message) => message.id)).toEqual([
      "assistant-partial",
      "terminal-error",
    ]);
    expect(projection.messages[0].content).toBe("你好，我在。");
    expect(projection.messages[0].feedbackEvents?.map((event) => event.name)).toEqual([
      "model_request",
    ]);
    expect(projection.messages[1].metadata?.kind).toBe("turn_error");
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
