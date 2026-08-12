import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { resolveAssistantDisplayPlan } from "./assistantDisplayPlan";
import type { CodexTranscriptSurface } from "./codexNativeTranscriptSurface";

function assistantMessage(patch: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message-1",
    role: "assistant",
    timestamp: "2026-08-09T00:00:00Z",
    turnId: "turn-1",
    status: "completed",
    turnItems: [],
    ...patch,
  };
}

function statusOnlyItem(): SessionTurnItem {
  return {
    id: "status-1-r0",
    itemId: "status-1",
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    type: "status",
    code: "user_submit",
    text: "已发送，正在连接",
    summary: "已发送，正在连接",
    status: "pending",
    revision: 0,
    sequence: 0,
    createdAt: "2026-08-09T00:00:00Z",
    updatedAt: "2026-08-09T00:00:00Z",
    terminal: false,
  };
}

function finalAnswerItem(text = "完成。"): SessionTurnItem {
  return {
    id: "answer-1-r1",
    itemId: "answer-1",
    version: 3,
    sessionId: "session-1",
    turnId: "turn-1",
    type: "agent_message",
    phase: "final_answer",
    text,
    status: "completed",
    revision: 1,
    sequence: 1,
  };
}

describe("assistantDisplayPlan canonical ownership", () => {
  it("assigns answer ownership only to turnItems", () => {
    const message = assistantMessage({
      turnItems: [finalAnswerItem()],
    });

    expect(resolveAssistantDisplayPlan({ message })).toMatchObject({
      protocol: "turn_items",
      answerOwner: "canonical_turn_items",
      renderMode: "turn_items",
      suppressProjectedResponse: true,
      hasTurnItemPackage: true,
    });
  });

  it("does not suppress when turnItems are status-only with no visible paint", () => {
    const message = assistantMessage({
      status: "pending",
      turnItems: [statusOnlyItem()],
    });
    const emptySurface: CodexTranscriptSurface = {
      mode: "native",
      source: "turnItems",
      cells: [],
    };

    expect(resolveAssistantDisplayPlan({ message, surface: emptySurface })).toMatchObject({
      hasTurnItemPackage: false,
      renderMode: "empty",
      nativePrimary: false,
      suppressProjectedResponse: false,
      suppressProjectedTurnStatus: false,
      shouldRenderCodexSurface: false,
    });
  });

  it("does not suppress empty in-flight shells so the placeholder path can work", () => {
    const message = assistantMessage({
      status: "pending",
      turnItems: [],
      metadata: { processStage: "user_submit" },
    });

    expect(resolveAssistantDisplayPlan({ message })).toMatchObject({
      hasTurnItemPackage: false,
      suppressProjectedResponse: false,
      suppressProjectedTurnStatus: false,
      renderMode: "empty",
    });
  });

  it("treats final_answer turnItems as a package when surface is omitted (tests)", () => {
    const message = assistantMessage({
      turnItems: [finalAnswerItem("完成。")],
    });

    expect(resolveAssistantDisplayPlan({ message })).toMatchObject({
      hasTurnItemPackage: true,
      suppressProjectedResponse: true,
      suppressProjectedTurnStatus: true,
      renderMode: "turn_items",
      answerOwner: "canonical_turn_items",
    });
  });

  it("counts canonical answers as visible paint even with empty native surface", () => {
    const message = assistantMessage({
      turnItems: [finalAnswerItem("完成。")],
    });
    const emptySurface: CodexTranscriptSurface = {
      mode: "native",
      source: "turnItems",
      cells: [],
    };

    expect(resolveAssistantDisplayPlan({ message, surface: emptySurface })).toMatchObject({
      hasTurnItemPackage: true,
      suppressProjectedResponse: true,
      suppressProjectedTurnStatus: true,
      renderMode: "turn_items",
      answerOwner: "canonical_turn_items",
      shouldRenderCodexSurface: false,
    });
  });

  it("suppresses when native surface has visible cells", () => {
    const message = assistantMessage({
      turnItems: [finalAnswerItem()],
    });
    const surface: CodexTranscriptSurface = {
      mode: "native",
      source: "turnItems",
      cells: [{
        id: "cell-1",
        kind: "assistant_markdown",
        messageId: "message-1",
        status: "completed",
        tone: "neutral",
        phase: "final_answer",
        text: "完成。",
      } as never],
    };

    expect(resolveAssistantDisplayPlan({ message, surface })).toMatchObject({
      hasTurnItemPackage: true,
      nativePrimary: true,
      suppressProjectedResponse: true,
      shouldRenderCodexSurface: true,
    });
  });
});
