import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../api/types";
import type { ActiveTurnLayerState } from "./chatActiveTurnLayer";
import {
  estimateGeneratedTokens,
  generatedTokenTextForMessage,
  latestStreamingAssistantMessage,
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
  tokenSpeedValueAt,
  tokenSpeedTextFromLayer,
} from "./chatTokenSpeed";

function assistantMessage(
  id: string,
  content: string,
  streaming = true,
): ConversationMessage {
  return {
    id,
    role: "assistant",
    content,
    timestamp: "2026-05-29T12:00:00Z",
    streaming,
  };
}

describe("chatTokenSpeed", () => {
  it("ignores tools, retries and terminal snapshots; samples only the latest generated text segment", () => {
    const layer: ActiveTurnLayerState = { id: "l", sessionId: "s", turnId: "t", status: "running", updatedAt: "", ledgerSeq: 1,
      turnItems: [{ id: "r", itemId: "r", version: 3, sessionId: "s", turnId: "t", sequence: 1, revision: 1,
        type: "reasoning", status: "completed", text: "可见思考" }] };
    expect(tokenSpeedTextFromLayer(layer)?.text).toBe("可见思考");
    layer.turnItems.push({ id: "retry", itemId: "retry", version: 3, sessionId: "s", turnId: "t", sequence: 2, revision: 1,
      type: "retry", status: "completed", attempt: 2, targetItemId: "r", reason: "retry" });
    expect(tokenSpeedTextFromLayer(layer)).toBeNull();
    layer.turnItems.push({ id: "a", itemId: "a", version: 3, sessionId: "s", turnId: "t", sequence: 3, revision: 1,
      type: "agent_message", phase: "final_answer", status: "running", text: "新一段回复" });
    expect(tokenSpeedTextFromLayer(layer)?.text).toBe("新一段回复");
    expect(tokenSpeedTextFromLayer({ ...layer, status: "completed" })).toBeNull();
    expect(tokenSpeedTextFromLayer(undefined)).toBeNull();
  });
  it("bounds sample history and resets when the clock reverses", () => {
    let tracker = updateTokenSpeedTracker(null, { sessionId: "s", messageId: "m", timestampMs: 0, tokenCount: 0 });
    for (let i = 1; i < 1000; i++) tracker = updateTokenSpeedTracker(tracker, { sessionId: "s", messageId: "m", timestampMs: i * 10, tokenCount: i });
    expect(tracker!.samples.length).toBeLessThanOrEqual(128);
    expect(tracker!.tokensPerSecond).toBeCloseTo(100);
    expect(updateTokenSpeedTracker(tracker, { sessionId: "s", messageId: "m", timestampMs: 1, tokenCount: 1000 })!.tokensPerSecond).toBeNull();
  });
  it("accumulates frequent chunks into a rolling window instead of resetting the clock", () => {
    let tracker = updateTokenSpeedTracker(null, { sessionId: "s", messageId: "request-1", tokenCount: 0, timestampMs: 0 });
    for (let time = 100; time <= 2000; time += 100) {
      tracker = updateTokenSpeedTracker(tracker, { sessionId: "s", messageId: "request-1", tokenCount: time / 100, timestampMs: time });
    }
    expect(tracker?.tokensPerSecond).toBeCloseTo(10);
    expect(tokenSpeedValueAt(tracker, 3600)).toBeNull();
    const resumed = updateTokenSpeedTracker(tracker, { sessionId: "s", messageId: "request-1", tokenCount: 21, timestampMs: 4000 });
    expect(resumed?.tokensPerSecond).toBeNull();
    expect(updateTokenSpeedTracker(resumed, { sessionId: "s2", messageId: "request-1", tokenCount: 24, timestampMs: 4500 })?.tokensPerSecond).toBeNull();
  });
  it("estimates generated tokens for mixed Chinese and Latin text", () => {
    expect(estimateGeneratedTokens("你好 world")).toBe(4);
    expect(estimateGeneratedTokens("abcd efgh")).toBe(2);
    expect(estimateGeneratedTokens("  ")).toBe(0);
  });
  it("does not count pre-answer progress text as generated output", () => {
    const messages = [
      assistantMessage("progress", "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。"),
    ];

    expect(tokenSpeedSampleFromMessages("session-1", messages, "running", 1000)).toBeNull();

    const queuedMessages = [
      assistantMessage("queued", "当前会话或 Agent 并发槽暂满，本轮已进入队列...\n会在同会话任务结束或 Agent 释放并发槽后继续执行。"),
    ];

    expect(tokenSpeedSampleFromMessages("session-1", queuedMessages, "queued", 1000)).toBeNull();
  });

  it("keeps the tracker reference when a query observer replays an unchanged token count", () => {
    const first = updateTokenSpeedTracker(null, {
      sessionId: "session-1",
      messageId: "message-1",
      tokenCount: 8,
      timestampMs: 1000,
    });

    const replay = updateTokenSpeedTracker(first, {
      sessionId: "session-1",
      messageId: "message-1",
      tokenCount: 8,
      timestampMs: 3000,
    });

    // Replayed React Query snapshots have a new timestamp but no new output.
    // Returning a new state object here schedules another render and can create
    // the ChatCodingRouteWorkbench update-depth loop.
    expect(replay).toBe(first);
  });

  it("computes token speed from positive streaming deltas and resets on new messages", () => {
    const first = updateTokenSpeedTracker(null, {
      sessionId: "session-1",
      messageId: "message-1",
      tokenCount: 4,
      timestampMs: 1000,
    });

    expect(first?.tokensPerSecond).toBeNull();

    const second = updateTokenSpeedTracker(first, {
      sessionId: "session-1",
      messageId: "message-1",
      tokenCount: 10,
      timestampMs: 2000,
    });

    expect(second?.tokensPerSecond).toBe(6);

    const reset = updateTokenSpeedTracker(second, {
      sessionId: "session-1",
      messageId: "message-2",
      tokenCount: 3,
      timestampMs: 2500,
    });

    expect(reset?.tokensPerSecond).toBeNull();
  });
});
