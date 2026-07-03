import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";

import type { ConversationMessage } from "../../api/types";
import {
  agentMessageTimelineItemRowKey,
  buildAgentMessageTimelineRowIdentities,
} from "./agentMessageTimelineRows";

const timelineRowsSource = readFileSync(new URL("./agentMessageTimelineRows.ts", import.meta.url), "utf8");

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

describe("AgentMessage timeline rows", () => {
  it("keeps AgentMessage timeline row helpers on AgentMessage-named files", () => {
    expect(existsSync(new URL("./agentMessageTimelineRows.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./conversationTimelineRows.ts", import.meta.url))).toBe(false);
  });

  it("exports row identity helpers through AgentMessage timeline naming only", () => {
    expect(timelineRowsSource).toContain("export type AgentMessageTimelineRowIdentity");
    expect(timelineRowsSource).toContain("export function buildAgentMessageTimelineRowIdentities");
    expect(timelineRowsSource).toContain("export function agentMessageTimelineItemRowKey");
    expect(timelineRowsSource).not.toContain("ConversationTimelineRowIdentity");
    expect(timelineRowsSource).not.toContain("buildConversationTimelineRowIdentities");
    expect(timelineRowsSource).not.toContain("conversationTimelineItemRowKey");
  });

  it("keeps same-turn live, active, and committed assistant packets on one stable row", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      content: "",
      streaming: true,
      metadata: { kind: "session_live_overlay", turnId: "live:turn-1" },
    });
    const activeLayer = assistantMessage("active-layer", {
      content: "流式回答",
      streaming: true,
      metadata: { kind: "session_active_turn_layer", turnId: "turn-1" },
    });
    const committed = assistantMessage("committed-answer", {
      content: "最终回答",
      streaming: false,
      metadata: { turnId: "turn-1" },
    });

    const [liveRow] = buildAgentMessageTimelineRowIdentities([liveOverlay]);
    const [activeRow] = buildAgentMessageTimelineRowIdentities([activeLayer]);
    const [committedRow] = buildAgentMessageTimelineRowIdentities([committed]);

    expect(liveRow.rowKey).toBe("assistant-turn:turn-1");
    expect(activeRow.rowKey).toBe(liveRow.rowKey);
    expect(committedRow.rowKey).toBe(liveRow.rowKey);
    expect(committedRow.processKey).toBe("assistant-turn:turn-1:process");
    expect(committedRow.answerKey).toBe("assistant-turn:turn-1:answer");
    expect(committedRow.processKey).not.toBe(committedRow.answerKey);
  });

  it("keeps duplicate same-turn rows unique when a user boundary prevents projection merging", () => {
    const rows = buildAgentMessageTimelineRowIdentities([
      assistantMessage("tool-before-user", { content: "", metadata: { turnId: "turn-shared" } }),
      {
        id: "user-message",
        role: "user",
        content: "继续",
        timestamp: "2026-06-29T10:00:01Z",
      },
      assistantMessage("answer-after-user", { metadata: { turnId: "turn-shared" } }),
    ]);

    expect(rows.map((row) => row.rowKey)).toEqual([
      "assistant-turn:turn-shared:message:tool-before-user",
      "user-message:user-message",
      "assistant-turn:turn-shared:message:answer-after-user",
    ]);
  });

  it("derives stable child keys for timeline items under the process part", () => {
    const [row] = buildAgentMessageTimelineRowIdentities([
      assistantMessage("message-with-timeline", { metadata: { turnId: "turn-timeline" } }),
    ]);

    expect(agentMessageTimelineItemRowKey(row, { id: "tool-1", kind: "operation" })).toBe(
      "assistant-turn:turn-timeline:process:item:operation:tool-1",
    );
  });
});
