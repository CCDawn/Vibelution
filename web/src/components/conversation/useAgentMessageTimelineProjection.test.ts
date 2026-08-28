import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
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
});
