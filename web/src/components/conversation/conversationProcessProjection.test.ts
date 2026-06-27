import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { projectConversationProcessMessages } from "./conversationProcessProjection";

function toolMessage(
  id: string,
  summary: string,
  patch: Partial<ConversationMessage> = {},
): ConversationMessage {
  return {
    id,
    role: "assistant",
    content: "",
    timestamp: "2026-06-26T14:56:00Z",
    feedbackEvents: [
      {
        sequence: 0,
        kind: "tool",
        status: "done",
        name: "apply_diff_edit_tool",
        summary,
      },
    ],
    metadata: { turnId: "turn-edit" },
    ...patch,
  };
}

describe("conversation process projection", () => {
  it("merges consecutive process-only messages from the same turn while preserving each tool event", () => {
    const projected = projectConversationProcessMessages([
      toolMessage("message-tool-1", "[编辑] 成功修改 config/public_config.py"),
      toolMessage("message-tool-2", "[编辑] 成功修改 config/workbench.py"),
      toolMessage("message-tool-3", "[编辑] 成功修改 config/settings.py"),
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0].id).toBe("message-tool-1");
    expect(projected[0].metadata?.projectedMessageIds).toEqual([
      "message-tool-1",
      "message-tool-2",
      "message-tool-3",
    ]);
    expect(projected[0].feedbackEvents?.map((event) => event.summary)).toEqual([
      "[编辑] 成功修改 config/public_config.py",
      "[编辑] 成功修改 config/workbench.py",
      "[编辑] 成功修改 config/settings.py",
    ]);
  });

  it("merges a same-turn process-only prefix into the following assistant answer", () => {
    const projected = projectConversationProcessMessages([
      toolMessage("message-tool-1", "[编辑] 成功修改 config/public_config.py"),
      toolMessage("message-tool-2", "[编辑] 成功修改 config/workbench.py"),
      {
        id: "message-answer",
        role: "assistant",
        content: "已完成修改。",
        timestamp: "2026-06-26T14:56:02Z",
        feedbackEvents: [
          {
            sequence: 3,
            kind: "thought",
            status: "done",
            summary: "整理最终回答",
          },
        ],
        metadata: { turnId: "turn-edit" },
      },
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0]).toMatchObject({
      id: "message-tool-1",
      content: "已完成修改。",
      metadata: {
        turnId: "turn-edit",
        projectedMessageIds: ["message-tool-1", "message-tool-2", "message-answer"],
      },
    });
    expect(projected[0].feedbackEvents?.map((event) => event.summary)).toEqual([
      "[编辑] 成功修改 config/public_config.py",
      "[编辑] 成功修改 config/workbench.py",
      "整理最终回答",
    ]);
  });

  it("merges same-turn process-only events that arrive after the assistant answer", () => {
    const projected = projectConversationProcessMessages([
      {
        id: "message-answer",
        role: "assistant",
        content: "整体结论：测试通过。",
        timestamp: "2026-06-27T16:14:20Z",
        metadata: { turnId: "turn-audit" },
      },
      toolMessage("message-tool-late", "[验证] pytest 通过", {
        timestamp: "2026-06-27T16:14:21Z",
        metadata: { turnId: "turn-audit" },
      }),
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0]).toMatchObject({
      id: "message-answer",
      content: "整体结论：测试通过。",
      metadata: {
        turnId: "turn-audit",
        projectedMessageIds: ["message-answer", "message-tool-late"],
      },
    });
    expect(projected[0].feedbackEvents?.map((event) => event.summary)).toEqual(["[验证] pytest 通过"]);
  });

  it("does not merge across user messages while merging the next same-turn answer packet", () => {
    const projected = projectConversationProcessMessages([
      toolMessage("message-tool-1", "[编辑] 成功修改 config/public_config.py"),
      {
        id: "message-user",
        role: "user",
        content: "继续",
        timestamp: "2026-06-26T14:56:01Z",
      },
      toolMessage("message-tool-2", "[编辑] 成功修改 config/workbench.py"),
      {
        id: "message-answer",
        role: "assistant",
        content: "已完成修改。",
        timestamp: "2026-06-26T14:56:02Z",
        feedbackEvents: [
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "apply_diff_edit_tool",
            summary: "[编辑] 成功修改 config/settings.py",
          },
        ],
        metadata: { turnId: "turn-edit" },
      },
    ]);

    expect(projected.map((message) => message.id)).toEqual([
      "message-tool-1",
      "message-user",
      "message-tool-2",
    ]);
    expect(projected[2].content).toBe("已完成修改。");
    expect(projected[2].metadata?.projectedMessageIds).toEqual(["message-tool-2", "message-answer"]);
  });

  it("does not merge adjacent process-only messages from different turn ids", () => {
    const projected = projectConversationProcessMessages([
      toolMessage("message-tool-1", "[编辑] 成功修改 config/public_config.py", { metadata: { turnId: "turn-a" } }),
      toolMessage("message-tool-2", "[编辑] 成功修改 config/workbench.py", { metadata: { turnId: "turn-b" } }),
    ]);

    expect(projected.map((message) => message.id)).toEqual(["message-tool-1", "message-tool-2"]);
  });
});
