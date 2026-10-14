import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import {
  collapseCompanionSpokenTexts,
  companionMessageSpokenText,
  companionUnrepeatedSpeech,
} from "./companionSpokenDisplay";

function assistant(turnItems: SessionTurnItem[]): ConversationMessage {
  return {
    id: "assistant-1",
    role: "assistant",
    content: "",
    timestamp: "2026-10-14T00:00:00Z",
    status: "completed",
    turnId: "turn-1",
    turnItems,
  };
}

function finalItem(itemId: string, text: string, sequence: number): SessionTurnItem {
  return {
    id: `${itemId}:1`,
    itemId,
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    type: "agent_message",
    phase: "final_answer",
    status: "completed",
    revision: 1,
    sequence,
    terminal: true,
    text,
  };
}

describe("companion spoken display", () => {
  it("collapses a later final answer that extends an earlier one", () => {
    expect(collapseCompanionSpokenTexts([
      "今天有点累",
      "今天有点累，想早点休息",
    ])).toBe("今天有点累，想早点休息");
  });

  it("keeps two different sentences from the same turn in one text", () => {
    expect(collapseCompanionSpokenTexts([
      "今天有点累",
      "明天再聊",
    ])).toBe("今天有点累\n\n明天再聊");
  });

  it("reads only final answers from a turn", () => {
    const message = assistant([
      {
        id: "reason:1",
        itemId: "reason",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "reasoning",
        status: "completed",
        revision: 1,
        sequence: 1,
        terminal: true,
        text: "内部思考",
      },
      {
        id: "note:1",
        itemId: "note",
        version: 3,
        sessionId: "session-1",
        turnId: "turn-1",
        type: "agent_message",
        phase: "commentary",
        status: "completed",
        revision: 1,
        sequence: 2,
        terminal: true,
        text: "过程说明",
      },
      finalItem("answer", "说给用户的话", 3),
    ]);
    expect(companionMessageSpokenText(message)).toBe("说给用户的话");
  });

  it("drops a follow-up that repeats the previous reply and keeps the new words", () => {
    expect(companionUnrepeatedSpeech("今天有点累", "今天有点累")).toBe("");
    expect(companionUnrepeatedSpeech("今天有点累", "今天有点累，想早点休息")).toBe("想早点休息");
    expect(companionUnrepeatedSpeech("今天有点累", "明天再聊")).toBe("明天再聊");
  });

  it("keeps a short reply that happens to sit inside a longer previous sentence", () => {
    expect(companionUnrepeatedSpeech("今天有点累，想早点休息", "好")).toBe("好");
  });
});
