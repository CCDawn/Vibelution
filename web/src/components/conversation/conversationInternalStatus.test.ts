import { describe, expect, it, vi } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  answerProjectionContent,
  compactStreamingStatusPlaceholder,
  isNoFinalAnswerStatusContent,
  messageHasInternalStreamingStatusContent,
  isStreamingStatusPlaceholderContent,
} from "./conversationInternalStatus";

describe("conversation internal status helpers", () => {
  it("keeps streaming status placeholder helpers out of ConversationView", () => {
    expect(conversationViewSource).toContain('from "./conversationInternalStatus"');
    expect(conversationViewSource).toContain("isStreamingStatusPlaceholderContent(responseText)");
    expect(conversationViewSource).toContain("compactStreamingStatusPlaceholder(responseText, compactPreview)");
    expect(conversationViewSource).not.toMatch(/function isStreamingStatusPlaceholderContent\(/);
    expect(conversationViewSource).not.toMatch(/function isNoFinalAnswerStatusContent\(/);
    expect(conversationViewSource).not.toMatch(/function compactStreamingStatusPlaceholder\(/);
  });

  it("recognizes internal streaming status placeholder text", () => {
    expect(isStreamingStatusPlaceholderContent("正在请求模型，等待首个响应片段")).toBe(true);
    expect(isStreamingStatusPlaceholderContent("这是用户可见的正常回答")).toBe(false);
  });

  it("keeps retry live overlay text out of the assistant answer projection", () => {
    const retryStatusText = "模型连接正在重试...\n第 2/5 次；原因：server_error。本轮仍在继续，请不要重复提交。";
    const message = {
      id: "message-model-retry-overlay",
      role: "assistant" as const,
      content: retryStatusText,
      timestamp: "2026-07-08T00:25:00Z",
      streaming: true,
      streamStage: "model_retry",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status" as const,
          status: "running" as const,
          name: "retrying",
          summary: retryStatusText,
          resultPreview: retryStatusText,
        },
      ],
      metadata: {
        kind: "session_live_overlay",
        turnId: "turn-retry",
      },
    };

    expect(isStreamingStatusPlaceholderContent(retryStatusText)).toBe(true);
    expect(messageHasInternalStreamingStatusContent(message)).toBe(true);
    expect(answerProjectionContent(message)).toBe("");
  });

  it("recognizes no-final-answer interruption status text", () => {
    expect(isNoFinalAnswerStatusContent(
      "本轮还没有形成最终回答，已保留当前执行进度；发送“继续”可衔接上一轮继续。",
    )).toBe(true);
    expect(isNoFinalAnswerStatusContent("本轮还没有形成最终回答，但这里只是普通说明。")).toBe(false);
    expect(isNoFinalAnswerStatusContent("")).toBe(false);
  });

  it("compacts non-internal streaming placeholders through the caller formatter", () => {
    const compactPreview = vi.fn((value: string, maxLength?: number) => `${maxLength}:${value}`);

    expect(compactStreamingStatusPlaceholder(
      "  正在处理\n更多内容  ",
      compactPreview,
    )).toBe("92:正在处理 更多内容");
    expect(compactPreview).toHaveBeenCalledWith("正在处理 更多内容", 92);

    expect(compactStreamingStatusPlaceholder(
      "正在请求模型，等待首个响应片段",
      compactPreview,
    )).toBe("");
  });
});
