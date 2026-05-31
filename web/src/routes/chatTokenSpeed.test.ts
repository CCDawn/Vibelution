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

  it("uses the latest streaming assistant response once answer text is available", () => {
    const messages = [
      assistantMessage("old", "上一段", false),
      assistantMessage("live", "正在生成新的回答"),
    ];

    expect(latestStreamingAssistantMessage(messages)?.id).toBe("live");
    expect(tokenSpeedSampleFromMessages("session-1", messages, "thinking", 1000)).toMatchObject({
      messageId: "live",
    });
    expect(tokenSpeedSampleFromMessages("session-1", messages, "answering", 1000)).toMatchObject({
      sessionId: "session-1",
      messageId: "live",
      tokenCount: 8,
      timestampMs: 1000,
    });
  });

  it("does not count pre-answer progress text as generated output", () => {
    const messages = [
      assistantMessage("progress", "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。"),
    ];

    expect(tokenSpeedSampleFromMessages("session-1", messages, "running", 1000)).toBeNull();
  });

  it("counts streaming thought and tool arguments when visible content is only progress text", () => {
    const messages: ConversationMessage[] = [
      {
        ...assistantMessage("live", "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。"),
        thought: "我正在把中文试卷需求转成图片生成提示词。",
        toolCalls: [
          {
            name: "image2_generate_tool",
            status: "running",
            arguments: {
              prompt: "A3 landscape Chinese math exam paper with geometry labels.",
            },
          },
        ],
      },
    ];

    expect(generatedTokenTextForMessage(messages[0])).toContain("中文试卷需求");
    expect(generatedTokenTextForMessage(messages[0])).toContain("A3 landscape");
    expect(latestStreamingAssistantMessage(messages)?.id).toBe("live");
    expect(tokenSpeedSampleFromMessages("session-1", messages, "tooling", 1000)).toMatchObject({
      sessionId: "session-1",
      messageId: "live",
      timestampMs: 1000,
    });
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
