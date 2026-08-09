import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../api/types";
import {
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
});
