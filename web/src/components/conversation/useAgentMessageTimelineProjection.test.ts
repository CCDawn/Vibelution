import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { assistantFinalAnswerText } from "../../routes/chatTurnProtocol";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import { buildAgentMessageOperations } from "./agentMessageOperations";
import { buildAgentMessageTimelineItems } from "./agentMessageTimeline";
import { buildStreamingTimelineScrollSignal } from "./conversationTimelineScrollSignals";
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
  it("keeps repeated received guidance before the live tail across snapshots and final settlement", () => {
    const turnId = "turn-steer";
    const item: SessionTurnItem = {
      version: 3,
      id: "answer",
      itemId: "answer",
      sessionId: "session-1",
      turnId,
      type: "agent_message",
      phase: "final_answer",
      status: "running",
      revision: 1,
      sequence: 1,
      terminal: false,
      text: "Answer before guidance",
    };
    const guidance: ConversationMessage[] = [58, 60].map((index) => ({
      id: `session-1-message-${index}`,
      role: "user",
      content: `Guidance ${index}`,
      timestamp: "2026-10-21T15:00:00Z",
      metadata: { kind: "user_guidance", source: "steer", turnId },
    }));
    const durable = assistantMessage("session-1-message-44", {
      turnId,
      status: "running",
      turnItems: [item],
      metadata: { turnId, messageIndex: 44 },
    });
    for (const revision of [2, 3]) {
      const active = assistantMessage("session-1-message-active-turn-steer", {
        turnId,
        status: "running",
        turnItems: [{ ...item, revision, text: `Answer continues ${revision}` }],
        metadata: { kind: "session_active_turn_layer", turnId },
      });
      const projection = projectAgentMessageTimelineMessages({
        timelineMessages: [durable, ...guidance],
        activeTurnMessage: active,
      });
      expect(projection.messages.map((message) => message.id)).toEqual([
        ...guidance.map((message) => message.id),
        durable.id,
      ]);
      expect(assistantFinalAnswerText(projection.messages.at(-1)!)).toBe(`Answer continues ${revision}`);
    }
    const completed = assistantMessage("session-1-message-62", {
      turnId,
      status: "completed",
      turnItems: [{ ...item, revision: 4, text: "Final answer", status: "completed", terminal: true }],
      metadata: { turnId, messageIndex: 62 },
    });
    const settled = projectAgentMessageTimelineMessages({ timelineMessages: [...guidance, completed] });
    expect(settled.messages.map((message) => message.id)).toEqual([
      ...guidance.map((message) => message.id),
      completed.id,
    ]);
  });

  it("keeps active-turn projection on an AgentMessage-named hook module", () => {
    expect(existsSync(new URL("./useAgentMessageTimelineProjection.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./useConversationTimelineProjection.ts", import.meta.url))).toBe(false);
  });it("drops process-only legacy DTO fields when no protocol event exists", () => {
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

  it("keeps incomplete live text revisions from crashing the strict renderer adapter", () => {
    const incompleteItem = (type: "agent_message" | "reasoning", sequence: number): SessionTurnItem => ({
      id: `${type}-${sequence}`,
      itemId: `${type}-${sequence}`,
      version: 3,
      sessionId: "session-live",
      turnId: "turn-live",
      status: "running",
      revision: 0,
      sequence,
      type,
      ...(type === "agent_message" ? { phase: "commentary" as const } : {}),
      text: undefined as unknown as string,
    });
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [{
        id: "live-turn",
        role: "assistant",
        turnId: "turn-live",
        status: "running",
        turnItems: [incompleteItem("reasoning", 1), incompleteItem("agent_message", 2)],
        timestamp: "2026-08-10T12:00:00Z",
      }],
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.agentMessages).toHaveLength(1);
    expect(projection.agentMessages[0]?.parts).toEqual([]);
  });

  it("keeps optimistic pending assistants with empty turnItems in the timeline", () => {
    const projection = projectAgentMessageTimelineMessages({
      activeTurnMessage: {
        id: "active-optimistic",
        role: "assistant",
        turnId: "optimistic",
        status: "pending",
        turnItems: [],
        timestamp: "2026-08-10T12:00:00Z",
        metadata: { processStage: "user_submit" },
      },
      timelineMessages: [],
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0]?.status).toBe("pending");
    expect(projection.messages[0]?.turnItems).toEqual([]);
  });

  it("drops an older process-only turn after a newer companion answer commits", () => {
    const staleReasoning: SessionTurnItem = {
      id: "reasoning-old:1", itemId: "reasoning-old", version: 3,
      sessionId: "session-1", turnId: "turn-old", type: "reasoning",
      status: "running", revision: 1, sequence: 1, terminal: false,
      text: "旧的内部思考不应继续显示",
      createdAt: "2026-08-28T13:18:00Z", updatedAt: "2026-08-28T13:18:00Z",
    };
    const finalAnswer: SessionTurnItem = {
      id: "answer-new:1", itemId: "answer-new", version: 3,
      sessionId: "session-1", turnId: "turn-new", type: "agent_message", phase: "final_answer",
      status: "completed", revision: 1, sequence: 2, terminal: true,
      text: "新的最终回复",
      createdAt: "2026-08-28T14:34:00Z", updatedAt: "2026-08-28T14:34:00Z",
    };
    const stale = assistantMessage("stale-running", {
      content: "", turnId: "turn-old", status: "running",
      turnItems: [staleReasoning], timestamp: "2026-08-28T13:18:00Z",
    });
    const committed = assistantMessage("new-final", {
      content: "", turnId: "turn-new", status: "completed",
      turnItems: [finalAnswer], timestamp: "2026-08-28T14:34:00Z",
    });

    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [committed, stale], companionMode: true,
    }).messages.map((message) => message.id)).toEqual(["new-final"]);
    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [committed, stale], companionMode: false,
    }).messages.map((message) => message.id)).toEqual(["new-final", "stale-running"]);
  });

  it("keeps a genuinely newer companion turn after historical terminal messages", () => {
    const historicalFinal: SessionTurnItem = {
      id: "answer-old:1", itemId: "answer-old", version: 3,
      sessionId: "session-1", turnId: "turn-old", type: "agent_message", phase: "final_answer",
      status: "completed", revision: 1, sequence: 1, terminal: true,
      text: "历史回复",
      createdAt: "2026-08-28T14:34:00Z", updatedAt: "2026-08-28T14:34:00Z",
    };
    const historical = assistantMessage("historical-final", {
      content: "", turnId: "turn-old", status: "completed",
      turnItems: [historicalFinal], timestamp: "2026-08-28T14:34:00Z",
    });
    const current = assistantMessage("current-running", {
      content: "", turnId: "turn-current", status: "running",
      turnItems: [], timestamp: "2026-08-28T14:35:00Z",
    });

    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [historical], activeTurnMessage: current, companionMode: true,
    }).messages.map((message) => message.id)).toEqual(["historical-final", "current-running"]);
  });

  it("hides a companion follow-up that repeats the previous reply", () => {
    const spoken = (id: string, text: string, timestamp: string) => assistantMessage(id, {
      content: "",
      turnId: id,
      status: "completed",
      timestamp,
      turnItems: [{
        id: `${id}:1`,
        itemId: id,
        version: 3,
        sessionId: "session-1",
        turnId: id,
        type: "agent_message",
        phase: "final_answer",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        text,
      }],
    });
    const first = spoken("first-reply", "今天有点累，想早点休息。", "2026-10-14T01:00:00Z");
    const repeat = spoken("repeat-reply", "今天有点累，想早点休息。", "2026-10-14T01:01:00Z");
    const extension = spoken("extension-reply", "今天有点累，想早点休息。明天再聊。", "2026-10-14T01:02:00Z");
    const user = {
      id: "user-again",
      role: "user" as const,
      content: "嗯",
      timestamp: "2026-10-14T01:03:00Z",
    };
    const afterUser = spoken("after-user", "今天有点累，想早点休息。", "2026-10-14T01:04:00Z");

    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [first, repeat],
      companionMode: true,
    }).messages.map((message) => message.id)).toEqual(["first-reply"]);
    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [first, repeat],
      companionMode: false,
    }).messages.map((message) => message.id)).toEqual(["first-reply", "repeat-reply"]);
    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [first, extension, user, afterUser],
      companionMode: true,
    }).messages.map((message) => message.id)).toEqual([
      "first-reply",
      "extension-reply",
      "user-again",
      "after-user",
    ]);
  });

  it("drops a settled companion turn that only has thinking", () => {
    const thinking = assistantMessage("thinking-only", {
      content: "",
      turnId: "turn-thinking",
      status: "completed",
      timestamp: "2026-10-14T02:00:00Z",
      turnItems: [{
        id: "thinking:1",
        itemId: "thinking",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-thinking",
        type: "reasoning",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        text: "这段思考不该占一条消息",
      }],
    });
    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [thinking],
      companionMode: true,
    }).messages).toEqual([]);
    expect(projectAgentMessageTimelineMessages({
      timelineMessages: [thinking],
      companionMode: false,
}).messages.map((message) => message.id)).toEqual(["thinking-only"]);
  });

  it.each([false, true])("preserves distinct durable turn items when a final answer is present: %s", (settled) => {
    const turnId = "turn-segments";
    const itemBase = {
      version: 3 as const,
      sessionId: "session-1",
      turnId,
      revision: 1,
      status: "completed" as const,
      terminal: true,
    };
    const tool: SessionTurnItem = {
      ...itemBase, id: "tool-1:1", itemId: "tool-1", sequence: 1,
      type: "tool_call", toolName: "read_file_tool",
    };
    const reasoning: SessionTurnItem = {
      ...itemBase, id: "reasoning-2:1", itemId: "reasoning-2", sequence: 2,
      type: "reasoning", text: "Inspecting the tool result",
    };
    const answer: SessionTurnItem = {
      ...itemBase, id: "answer-3:1", itemId: "answer-3", sequence: 3,
      type: "agent_message", phase: "final_answer", text: "Completed answer",
    };
    const durableItems = settled ? [tool, reasoning, answer] : [tool, reasoning];
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: durableItems.map((item, index) => ({
        id: `session-1-message-segment-${index}`,
        role: "assistant" as const,
        turnId,
        status: "completed" as const,
        timestamp: `2026-10-17T12:00:0${index}Z`,
        turnItems: [item],
      })),
      ...(settled ? {
        activeTurnMessage: {
          id: "session-1-message-active-turn-segments",
          role: "assistant" as const,
          turnId,
          status: "running" as const,
          timestamp: "2026-10-17T12:00:03Z",
          turnItems: [{
            ...answer, id: "stale-answer:1", itemId: "stale-answer",
            status: "running" as const, terminal: false, text: "Incomplete answer",
          }],
          metadata: { kind: "session_active_turn_layer", turnId },
        },
      } : {}),
    });

    expect(projection.messages).toHaveLength(1);
    const message = projection.messages[0];
    expect(message?.role).toBe("assistant");
    if (message?.role !== "assistant") throw new Error("Expected an assistant row");
    expect(message.turnItems.map((item) => item.itemId)).toEqual(durableItems.map((item) => item.itemId));
    expect(message.metadata?.projectedMessageIds).toEqual(
      durableItems.map((_, index) => `session-1-message-segment-${index}`),
    );
  });

  it("renders one assistant row when a backend live overlay and the active turn layer share a turn", () => {
    const inFlightItem = (owner: string): SessionTurnItem => ({
      id: `${owner}:1`,
      itemId: owner,
      version: 3,
      sessionId: "session-1",
      turnId: "turn-dupe",
      type: "agent_message",
      phase: "final_answer",
      status: "running",
      revision: 1,
      sequence: 1,
      terminal: false,
      text: "正在输出的同一段回答",
    });
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [{
        id: "session-1-message-durable-tool",
        role: "assistant",
        turnId: "turn-dupe",
        status: "completed",
        timestamp: "2026-10-17T11:59:59Z",
        turnItems: [{
          ...inFlightItem("persisted-tool"),
          type: "tool_call",
          toolName: "read_file_tool",
          status: "completed",
          terminal: true,
          sequence: 0,
        }],
      }, {
        id: "session-1-message-live-turn-dupe",
        role: "assistant",
        turnId: "turn-dupe",
        status: "running",
        timestamp: "2026-10-17T12:00:00Z",
        turnItems: [inFlightItem("live")],
        metadata: { kind: "session_live_overlay", turnId: "turn-dupe" },
      }],
      activeTurnMessage: {
        id: "session-1-message-active-turn-dupe",
        role: "assistant",
        turnId: "turn-dupe",
        status: "running",
        timestamp: "2026-10-17T12:00:01Z",
        turnItems: [inFlightItem("active")],
        metadata: { kind: "session_active_turn_layer", turnId: "turn-dupe" },
      },
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0]?.id).toBe("session-1-message-active-turn-dupe");
    expect(projection.messages[0]?.role === "assistant" && projection.messages[0].turnItems.map((item) => item.itemId))
      .toEqual(["persisted-tool", "active"]);
  });

  it("keeps the streaming backend overlay when the active turn layer is an empty shell", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [{
        id: "session-1-message-live-turn-shell",
        role: "assistant",
        turnId: "turn-shell",
        status: "running",
        timestamp: "2026-10-17T12:00:00Z",
        turnItems: [{
          id: "live-text:1",
          itemId: "live-text",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-shell",
          type: "agent_message",
          phase: "final_answer",
          status: "running",
          revision: 1,
          sequence: 1,
          terminal: false,
          text: "后端投影已经流出的正文",
        }],
        metadata: { kind: "session_live_overlay", turnId: "turn-shell" },
      }],
      activeTurnMessage: {
        id: "session-1-message-active-turn-shell",
        role: "assistant",
        turnId: "turn-shell",
        status: "pending",
        timestamp: "2026-10-17T12:00:01Z",
        turnItems: [],
        metadata: { kind: "session_active_turn_layer", turnId: "turn-shell", processStage: "user_submit" },
      },
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0]?.id).toBe("session-1-message-live-turn-shell");
  });

  it("retires a stale active turn overlay once the same turn committed its answer", () => {
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [{
        id: "session-1-message-12",
        role: "assistant",
        turnId: "turn-committed",
        status: "completed",
        timestamp: "2026-10-17T12:00:02Z",
        turnItems: [{
          id: "answer:1",
          itemId: "answer",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-committed",
          type: "agent_message",
          phase: "final_answer",
          status: "completed",
          revision: 2,
          sequence: 1,
          terminal: true,
          text: "已经提交的最终回答",
        }],
      }],
      activeTurnMessage: {
        id: "session-1-message-active-turn-committed",
        role: "assistant",
        turnId: "turn-committed",
        status: "running",
        timestamp: "2026-10-17T12:00:01Z",
        turnItems: [{
          id: "answer-stale:1",
          itemId: "answer-stale",
          version: 3,
          sessionId: "session-1",
          turnId: "turn-committed",
          type: "agent_message",
          phase: "final_answer",
          status: "running",
          revision: 1,
          sequence: 1,
          terminal: false,
          text: "已经提交的最终",
        }],
        metadata: { kind: "session_active_turn_layer", turnId: "turn-committed" },
      },
    });

expect(projection.messages).toHaveLength(1);
    expect(projection.messages[0]?.id).toBe("session-1-message-12");
  });

  it("gives the deduped overlay one row identity and one streaming scroll signal", () => {
    const inFlightItem = (owner: string): SessionTurnItem => ({
      id: `${owner}:1`,
      itemId: owner,
      version: 3,
      sessionId: "session-1",
      turnId: "turn-signal",
      type: "agent_message",
      phase: "final_answer",
      status: "running",
      revision: 1,
      sequence: 1,
      terminal: false,
      text: "同一 turn 的在途正文",
    });
    const projection = projectAgentMessageTimelineMessages({
      timelineMessages: [{
        id: "session-1-message-live-turn-signal",
        role: "assistant",
        content: "",
        turnId: "turn-signal",
        status: "running",
        timestamp: "2026-10-17T12:00:00Z",
        turnItems: [inFlightItem("live")],
        metadata: { kind: "session_live_overlay", turnId: "turn-signal" },
      }],
      activeTurnMessage: {
        id: "session-1-message-active-turn-signal",
        role: "assistant",
        content: "",
        turnId: "turn-signal",
        status: "running",
        timestamp: "2026-10-17T12:00:01Z",
        turnItems: [inFlightItem("active")],
        metadata: { kind: "session_active_turn_layer", turnId: "turn-signal" },
      },
    });

    expect(projection.messages).toHaveLength(1);
    expect(projection.rowIdentities).toHaveLength(1);
    expect(projection.rowIdentities[0]?.messageId).toBe("session-1-message-active-turn-signal");
    expect(projection.streamingMessages).toHaveLength(1);
    const signal = buildStreamingTimelineScrollSignal(projection.streamingMessages, new Map());
    expect(signal.split("|")).toHaveLength(1);
    expect(signal.startsWith("session-1-message-active-turn-signal:")).toBe(true);
  });
});
