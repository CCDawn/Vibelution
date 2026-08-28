import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../api/types";
import {
  assistantTurnIsInFlight,
  assistantTurnIsStreaming,
  codexTranscriptFromTurnItems,
  consolidateSessionTurnItemsV2,
  hasCommittedAssistantProtocolAnswer,
  projectConversationMessageFromTurnItemsV2,
} from "./chatTurnProtocol";

const base = { version: 3, sessionId: "session-1", turnId: "turn-1" } as const;

describe("canonical SessionTurnItem v3 rendering", () => {
  it("keeps the highest revision and one final answer", () => {
    const items: SessionTurnItem[] = [
      { ...base, id: "answer-r1", itemId: "answer", type: "agent_message", phase: "final_answer", text: "旧", status: "running", revision: 1, sequence: 1 },
      { ...base, id: "answer-r2", itemId: "answer", type: "agent_message", phase: "final_answer", text: "新", status: "completed", revision: 2, sequence: 1 },
    ];
    const consolidated = consolidateSessionTurnItemsV2(items);
    expect(consolidated).toHaveLength(1);
    expect(consolidated[0]).toMatchObject({ id: "answer-r2", text: "新" });
  });

  it("projects one assistant turn without legacy top-level content", () => {
    const item: SessionTurnItem = {
      ...base, id: "answer-r1", itemId: "answer", type: "agent_message", phase: "final_answer",
      text: "完成。", status: "completed", revision: 1, sequence: 1, terminal: true,
    };
    const message = projectConversationMessageFromTurnItemsV2({
      id: "message-1", role: "assistant", timestamp: "2026-08-09T00:00:00Z",
      turnId: "turn-1", status: "completed", turnItems: [item],
    }) as ConversationMessage;
    expect(hasCommittedAssistantProtocolAnswer(message)).toBe(true);
    expect(message).not.toHaveProperty("content");
  });

  it("does not keep a contradictory running message in flight after a terminal item", () => {
    const item: SessionTurnItem = {
      ...base, id: "answer-terminal", itemId: "answer", type: "agent_message", phase: "final_answer",
      text: "已经完成。", status: "completed", revision: 1, sequence: 1, terminal: true,
    };
    const staleRunningMessage: ConversationMessage = {
      id: "message-stale-running", role: "assistant", timestamp: "2026-08-28T11:00:00Z",
      turnId: "turn-1", status: "running", turnItems: [item],
    };

    expect(assistantTurnIsStreaming(staleRunningMessage)).toBe(false);
    expect(assistantTurnIsInFlight(staleRunningMessage)).toBe(false);
  });

  it("keeps the turn running when only a commentary child item is terminal", () => {
    const commentary: SessionTurnItem = {
      ...base, id: "commentary-terminal", itemId: "commentary", type: "agent_message",
      phase: "commentary", text: "上一段过程已经完成。", status: "completed", revision: 1,
      sequence: 1, terminal: true,
    };
    const reasoning: SessionTurnItem = {
      ...base, id: "reasoning-running", itemId: "reasoning", type: "reasoning",
      text: "仍在继续思考。", status: "running", revision: 1, sequence: 2, terminal: false,
    };
    const runningMessage: ConversationMessage = {
      id: "message-still-running", role: "assistant", timestamp: "2026-08-28T11:00:00Z",
      turnId: "turn-1", status: "running", turnItems: [commentary, reasoning],
    };

    expect(assistantTurnIsStreaming(runningMessage)).toBe(true);
    expect(assistantTurnIsInFlight(runningMessage)).toBe(true);
  });

  it("keeps the rendered tool row identity stable across revisions", () => {
    const running: SessionTurnItem = {
      ...base, id: "tool-r0", itemId: "tool", type: "tool_call", callId: "call-1", toolName: "glob_tool",
      status: "running", revision: 0, sequence: 1,
    };
    const completed: SessionTurnItem = {
      ...running, id: "tool-r1", status: "completed", revision: 1, output: "done",
    };

    expect(codexTranscriptFromTurnItems([running]).cells[0]?.id).toBe("tool");
    expect(codexTranscriptFromTurnItems([completed]).cells[0]?.id).toBe("tool");
  });

  it("uses the human compression marker title instead of its internal status code", () => {
    const marker: SessionTurnItem = {
      ...base,
      id: "compression-applied:0",
      itemId: "compression-applied",
      type: "status",
      code: "context_compression_applied",
      title: "上下文已压缩",
      text: "standard · 节省 5,800 tokens · 自动阈值",
      status: "completed",
      revision: 0,
      sequence: 1,
      terminal: true,
    };

    expect(codexTranscriptFromTurnItems([marker]).cells[0]).toMatchObject({
      kind: "status",
      title: "上下文已压缩",
      text: "standard · 节省 5,800 tokens · 自动阈值",
    });
  });

  it("preserves an exact tool start from an older-sequence live enrichment", () => {
    const cached: SessionTurnItem = {
      ...base, id: "tool-cached", itemId: "tool", type: "tool_call", callId: "call-1",
      toolName: "grep_search_tool", status: "running", revision: 1, sequence: 8,
      updatedAt: "2026-08-10T00:00:00Z",
    };
    const exactStart: SessionTurnItem = {
      ...cached, id: "tool-live", sequence: 7,
      metadata: { executionStartedAtEpochMs: 1_786_294_806_000 },
    };

    expect(consolidateSessionTurnItemsV2([cached], [exactStart])).toEqual([
      expect.objectContaining({
        id: "tool-cached",
        sequence: 8,
        metadata: { executionStartedAtEpochMs: 1_786_294_806_000 },
      }),
    ]);
  });
});
