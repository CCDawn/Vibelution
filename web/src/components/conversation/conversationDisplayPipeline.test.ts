import { describe, expect, it, beforeEach } from "vitest";

import type { ConversationMessage, SessionTurnItem } from "../../api/types";
import { projectConversationDisplayPipeline } from "./conversationDisplayPipeline";
import {
  inspectConversationDisplayMessages,
  projectConversationDisplayMessages,
} from "./conversationDisplayMessages";
import {
  readConversationDisplayTelemetry,
  recordConversationSurfaceBuild,
  resetConversationDisplayTelemetry,
} from "./conversationDisplayTelemetry";

const turnBase = { version: 3, sessionId: "session-1", turnId: "turn-1" } as const;

function turnItem(
  itemId: string,
  sequence: number,
  text: string,
  overrides: Partial<SessionTurnItem> = {},
): SessionTurnItem {
  return {
    ...turnBase,
    id: `${itemId}-r${sequence}`,
    itemId,
    type: "agent_message",
    phase: "final_answer",
    text,
    status: "completed",
    revision: 1,
    sequence,
    terminal: true,
    ...overrides,
  } as SessionTurnItem;
}

function assistantMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "assistant-message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T21:44:00Z",
    turnId: "turn-1",
    status: "completed",
    turnItems: [],
    ...overrides,
  } as ConversationMessage;
}

function userMessage(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return {
    id: "user-message",
    role: "user",
    content: "question",
    timestamp: "2026-07-03T21:43:00Z",
    ...overrides,
  } as ConversationMessage;
}

beforeEach(() => {
  resetConversationDisplayTelemetry();
});

describe("conversation display pipeline", () => {
  it("folds same-turn assistant segments before suppressing anything", () => {
    const result = projectConversationDisplayPipeline([
      userMessage({ id: "user-1" }),
      assistantMessage({
        id: "assistant-segment-a",
        turnItems: [turnItem("answer", 1, "first half")],
      }),
      assistantMessage({
        id: "assistant-segment-b",
        // Interleaved noise between two segments of the same turn: adjacency
        // comparison would miss this, identity folding must not.
        turnItems: [turnItem("answer-2", 2, "second half")],
      }),
    ]);

    const foldStage = result.stages.find((stage) => stage.stage === "fold");
    expect(foldStage).toEqual({ stage: "fold", inputCount: 3, outputCount: 2 });
    expect(result.messages.map((message) => message.id)).toEqual([
      "user-1",
      "assistant-segment-a",
    ]);
    expect(result.messages[1].turnItems.map((item) => item.text)).toEqual([
      "first half",
      "second half",
    ]);
  });

  it("records one discard reason per dropped row, in rule order", () => {
    const result = projectConversationDisplayPipeline([
      userMessage({ id: "user-kept" }),
assistantMessage({
        id: "runtime-notice",
        // Runtime notices are status turn items, not a metadata kind: the
        // predicate reads the item text, so the fixture must speak that shape.
        turnItems: [
          turnItem("notice", 1, "上一轮运行已被中断，当前会话已恢复为可继续状态", {
            type: "status",
          } as Partial<SessionTurnItem>),
        ],
      }),      assistantMessage({
        id: "superseded-partial",
        metadata: { interrupted: true, recoverySuperseded: true },
      }),
      userMessage({
        id: "resume-duplicate",
        content: "question",
        metadata: { kind: "hot_restart_resume" },
      }),
    ]);

    expect(result.messages.map((message) => message.id)).toEqual(["user-kept"]);
    expect(result.decisions.map((decision) => decision.reason)).toEqual([
      "runtime_notice",
      "recovery_superseded",
      "hot_restart_resume",
    ]);
    expect(result.decisions.every((decision) => decision.stage === "suppress")).toBe(true);
  });

  it("keeps the historical entry point behaviour-identical to the pipeline", () => {
    const messages = [
      userMessage({ id: "user-1" }),
      assistantMessage({
        id: "assistant-segment-a",
        turnItems: [turnItem("answer", 1, "answer text")],
      }),
      assistantMessage({
        id: "runtime-notice",
        metadata: { kind: "runtime_notice" },
      }),
    ];

    expect(projectConversationDisplayMessages(messages).map((message) => message.id)).toEqual(
      projectConversationDisplayPipeline(messages).messages.map((message) => message.id),
    );
    expect(inspectConversationDisplayMessages(messages).stages.map((stage) => stage.stage)).toEqual([
      "canonical",
      "order",
      "fold",
      "suppress",
    ]);
  });
});

describe("conversation display telemetry", () => {
  it("counts discards per reason and marks a full rebuild frame", () => {
    projectConversationDisplayMessages([
      userMessage({ id: "user-1" }),
      userMessage({ id: "resume-duplicate", metadata: { kind: "hot_restart_resume" } }),
    ]);

    const snapshot = readConversationDisplayTelemetry();
    expect(snapshot.frameTotal).toBe(1);
    expect(snapshot.lastFrame?.discarded.hot_restart_resume).toBe(1);
    expect(snapshot.lastFrame?.inputCount).toBe(2);
    expect(snapshot.lastFrame?.visibleCount).toBe(1);
    expect(snapshot.fullRebuildFrames).toBe(1);
  });

  it("keeps a bounded ring buffer and the latest surface build sample", () => {
    for (let index = 0; index < 260; index += 1) {
      projectConversationDisplayMessages([userMessage({ id: `user-${index}` })]);
    }
    recordConversationSurfaceBuild({ totalMessages: 40, rebuiltMessages: 2, durationMs: 1.5 });

    const snapshot = readConversationDisplayTelemetry();
    expect(snapshot.frameTotal).toBe(260);
    expect(snapshot.frames.length).toBe(240);
    expect(snapshot.lastSurfaceBuild).toEqual({
      at: expect.any(String),
      totalMessages: 40,
      rebuiltMessages: 2,
      durationMs: 1.5,
    });
  });
});
