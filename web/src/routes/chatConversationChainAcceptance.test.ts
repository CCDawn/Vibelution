import { describe, expect, it } from "vitest";

import type { SessionStreamEvent, SessionTurnItem } from "../api/types";
import fixture from "../../../tests/fixtures/conversation_chain/canonical_tool_followup_v2.json";
import {
  activeTurnLayerToConversationMessage,
  mergeAssistantDeltaIntoActiveTurnLayer,
  type ActiveTurnLayerState,
} from "./chatActiveTurnLayer";

type AssistantDelta = Extract<SessionStreamEvent, { type: "assistant_delta" }>;

describe("shared canonical conversation-chain acceptance", () => {
  it("keeps repeated user text distinct through canonical turn identity", () => {
    const [first, second] = fixture.turns;

    expect(first.user_text).toBe("继续");
    expect(second.user_text).toBe("继续");
    expect(first.turn_id).not.toBe(second.turn_id);
    expect(first.invocation_id).not.toBe(second.invocation_id);
    expect(first.submission_id).not.toBe(second.submission_id);
    expect(first.session_id).toBe(second.session_id);
  });

  it("projects parallel tool revisions and one terminal final without stale processing UI", () => {
    const events = fixture.frontend.stream_events as unknown as AssistantDelta[];
    const terminalTurn = fixture.turns[1];
    let active: ActiveTurnLayerState | undefined;

    for (const event of events) {
      active = mergeAssistantDeltaIntoActiveTurnLayer(active, event);
    }

    const message = activeTurnLayerToConversationMessage(active);
    const items = (message?.turnItems ?? []) as SessionTurnItem[];
    const cells = message?.codexTranscript?.cells ?? [];
    const toolItems = items.filter((item) => item.kind === "tool_call");
    const finalItems = items.filter(
      (item) => item.kind === "assistant_message"
        && item.channel === "answer"
        && item.phase === "final_answer",
    );
    const terminalText = cells.map((cell) => cell.text ?? cell.summary ?? cell.title ?? "").join("\n");

    expect(active?.streaming).toBe(false);
    expect(message?.content).toBe("第二轮完成：天气晴朗，且语义历史与 wire parity 均已确认。");
    expect(items.map((item) => item.itemId)).toEqual([
      "status-processing-002",
      "tool-weather-002",
      "tool-notes-002",
      "final-answer-002",
    ]);
    expect(new Set(items.map((item) => item.itemId)).size).toBe(items.length);
    expect(toolItems).toHaveLength(2);
    expect(toolItems.map((item) => item.callId)).toEqual(["call-weather-002", "call-notes-002"]);
    expect(toolItems.every((item) => item.status === "completed")).toBe(true);
    expect(finalItems).toHaveLength(1);
    expect(finalItems[0]).toMatchObject({ status: "completed", terminal: true, provisional: false });
    expect(items.some((item) => ["running", "pending", "in_progress"].includes(item.status))).toBe(false);
    expect(terminalText).not.toContain("正在处理");
    expect(cells.filter((cell) => cell.kind === "tool_call")).toHaveLength(2);
    expect(cells.filter((cell) => cell.kind === "assistant_markdown" && cell.phase === "final_answer")).toHaveLength(1);

    for (const item of items) {
      expect(item.sessionId).toBe(terminalTurn.session_id);
      expect(item.turnId).toBe(terminalTurn.turn_id);
      expect(item.invocationId).toBe(terminalTurn.invocation_id);
      expect(item.metadata?.submissionId).toBe(terminalTurn.submission_id);
    }
  });
});
