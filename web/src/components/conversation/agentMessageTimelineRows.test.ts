import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";

import type { AgentMessage } from "../../agent-thread";
import {
  agentMessageTimelineItemRowKey,
  buildAgentMessageTimelineRowIdentities,
} from "./agentMessageTimelineRows";

const timelineRowsSource = readFileSync(new URL("./agentMessageTimelineRows.ts", import.meta.url), "utf8");

function assistantMessage(
  id: string,
  patch: Partial<AgentMessage> = {},
): AgentMessage {
  return {
    id,
    role: "assistant",
    createdAt: "2026-06-29T10:00:00Z",
    streaming: false,
    turnId: "turn-1",
    source: { kind: "conversation-message", id },
    parts: [{ id: `${id}-text`, type: "text", channel: "answer", text: "回答正文" }],
    ...patch,
  };
}

function userMessage(id: string, patch: Partial<AgentMessage> = {}): AgentMessage {
  return {
    id,
    role: "user",
    createdAt: "2026-06-29T10:00:01Z",
    streaming: false,
    source: { kind: "conversation-message", id },
    parts: [{ id: `${id}-text`, type: "text", channel: "user", text: "继续" }],
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

  it("derives row identities from AgentMessage projections instead of ConversationMessage DTOs", () => {
    expect(timelineRowsSource).not.toContain("../../api/types");
    expect(timelineRowsSource).not.toContain("ConversationMessage");
  });

  it("keeps same-turn live, active, and committed assistant packets on one stable row", () => {
    const liveOverlay = assistantMessage("live-overlay", {
      streaming: true,
      turnId: "turn-1",
      source: { kind: "conversation-message", id: "live-overlay", metadata: { kind: "session_live_overlay" } },
      parts: [],
    });
    const activeLayer = assistantMessage("active-layer", {
      streaming: true,
      turnId: "turn-1",
      source: { kind: "conversation-message", id: "active-layer", metadata: { kind: "session_active_turn_layer" } },
    });
    const committed = assistantMessage("committed-answer", {
      streaming: false,
      turnId: "turn-1",
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

  it("keeps an active Agent row stable while its canonical turn id is bound", () => {
    const optimistic = assistantMessage("session-1-message-active-optimistic", {
      streaming: true,
      turnId: "optimistic-submit",
      source: {
        kind: "conversation-message",
        id: "session-1-message-active-optimistic",
        metadata: {
          kind: "session_active_turn_layer",
          renderKey: "session-1-active",
        },
      },
      parts: [],
    });
    const bound = assistantMessage("session-1-message-active-turn-accepted", {
      streaming: true,
      turnId: "turn-accepted",
      source: {
        kind: "conversation-message",
        id: "session-1-message-active-turn-accepted",
        metadata: {
          kind: "session_active_turn_layer",
          renderKey: "session-1-active",
        },
      },
      parts: [],
    });

    const [optimisticRow] = buildAgentMessageTimelineRowIdentities([optimistic]);
    const [boundRow] = buildAgentMessageTimelineRowIdentities([bound]);

    expect(optimisticRow.rowKey).toBe("assistant-active:session-1-active");
    expect(boundRow.rowKey).toBe(optimisticRow.rowKey);
  });

  it("keeps an optimistic user row stable when its authoritative message arrives", () => {
    const optimistic = userMessage("optimistic-user-submission-1", {
      metadata: { clientSubmissionId: "submission-1" },
    });
    const committed = userMessage("session-1-message-9", {
      source: {
        kind: "conversation-message",
        id: "session-1-message-9",
        metadata: { clientSubmissionId: "submission-1" },
      },
    });

    const [optimisticRow] = buildAgentMessageTimelineRowIdentities([optimistic]);
    const [committedRow] = buildAgentMessageTimelineRowIdentities([committed]);

    expect(optimisticRow.rowKey).toBe("user-submission:submission-1");
    expect(committedRow.rowKey).toBe(optimisticRow.rowKey);
  });

  it("keeps duplicate same-turn rows unique when a user boundary prevents projection merging", () => {
    const rows = buildAgentMessageTimelineRowIdentities([
      assistantMessage("tool-before-user", { turnId: "turn-shared" }),
      userMessage("user-message"),
      assistantMessage("answer-after-user", { turnId: "turn-shared" }),
    ]);

    expect(rows.map((row) => row.rowKey)).toEqual([
      "assistant-turn:turn-shared:message:tool-before-user",
      "user-message:user-message",
      "assistant-turn:turn-shared:message:answer-after-user",
    ]);
  });

  it("derives stable child keys for timeline items under the process part", () => {
    const [row] = buildAgentMessageTimelineRowIdentities([
      assistantMessage("message-with-timeline", { turnId: "turn-timeline" }),
    ]);

    expect(agentMessageTimelineItemRowKey(row, { id: "tool-1", kind: "operation" })).toBe(
      "assistant-turn:turn-timeline:process:item:operation:tool-1",
    );
  });
});
