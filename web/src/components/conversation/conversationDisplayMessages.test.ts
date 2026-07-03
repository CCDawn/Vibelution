import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";

const displayMessagesModulePath = new URL("./conversationDisplayMessages.ts", import.meta.url);
const conversationViewSource = readFileSync(new URL("./ConversationView.tsx", import.meta.url), "utf8");

async function projectConversationDisplayMessages(messages: ConversationMessage[]) {
  if (!existsSync(displayMessagesModulePath)) {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
  }
  const module = await import("./conversationDisplayMessages");
  return module.projectConversationDisplayMessages(messages);
}

function message(overrides: Partial<ConversationMessage>): ConversationMessage {
  return {
    id: "message",
    role: "assistant",
    content: "",
    timestamp: "2026-07-03T21:44:00Z",
    ...overrides,
  };
}

describe("conversation display message projection", () => {
  it("keeps ConversationView from owning display message DTO merge rules", () => {
    expect(existsSync(displayMessagesModulePath)).toBe(true);
    expect(conversationViewSource).toContain("projectConversationDisplayMessages");
    expect(conversationViewSource).not.toContain("function mergeAdjacentTurnErrorMessages");
    expect(conversationViewSource).not.toContain("const mergedMessages: ConversationMessage[]");
  });

  it("filters runtime notices before display projection", async () => {
    const projected = await projectConversationDisplayMessages([
      message({
        id: "runtime-notice",
        content: "上一轮运行已被中断，当前会话已恢复为可继续状态。",
      }),
      message({
        id: "answer",
        content: "可见回答",
      }),
    ]);

    expect(projected.map((item) => item.id)).toEqual(["answer"]);
  });

  it("merges adjacent duplicate turn errors while keeping the newest mental snapshot", async () => {
    const projected = await projectConversationDisplayMessages([
      message({
        id: "turn-error-1",
        content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
        thought: "first failure thought",
        toolCalls: [{ name: "image2_generate_tool", status: "done", summary: "failed" }],
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "image2_generate_tool",
            summary: "failed",
          },
        ],
        mentalSnapshot: {
          feeling: "previous",
          summary: "old snapshot",
          trust: 0.2,
        },
        metadata: {
          kind: "turn_error",
          errorType: "RuntimeError",
        },
      }),
      message({
        id: "turn-error-2",
        content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
        thought: "second failure thought",
        toolCalls: [{ name: "image2_generate_tool", status: "done", summary: "failed" }],
        feedbackEvents: [
          {
            sequence: 2,
            kind: "thought",
            status: "done",
            summary: "diagnosed provider limit",
          },
        ],
        mentalSnapshot: {
          feeling: "current",
          summary: "new snapshot",
          trust: 0.4,
        },
        metadata: {
          kind: "turn_error",
          httpStatus: 429,
        },
      }),
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0]).toMatchObject({
      id: "turn-error-1",
      thought: "first failure thought\n\nsecond failure thought",
      mentalSnapshot: {
        feeling: "current",
        summary: "new snapshot",
      },
      metadata: {
        kind: "turn_error",
        errorType: "RuntimeError",
        httpStatus: 429,
      },
    });
    expect(projected[0].toolCalls).toHaveLength(1);
    expect(projected[0].feedbackEvents?.map((event) => event.summary)).toEqual([
      "failed",
      "diagnosed provider limit",
    ]);
  });
});
