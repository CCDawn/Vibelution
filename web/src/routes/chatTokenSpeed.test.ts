import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../api/types";
import {
  estimateGeneratedTokens,
  generatedTokenTextForMessage,
  latestStreamingAssistantMessage,
  tokenSpeedSampleFromMessages,
  updateTokenSpeedTracker,
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
