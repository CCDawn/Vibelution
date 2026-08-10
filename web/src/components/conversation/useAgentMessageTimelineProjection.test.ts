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
});
