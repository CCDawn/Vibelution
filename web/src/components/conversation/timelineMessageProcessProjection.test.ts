import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { projectTimelineProcessMessages } from "./timelineMessageProcessProjection";

const timelineProcessProjectionModulePath = new URL("./timelineMessageProcessProjection.ts", import.meta.url);
const retiredAgentMessageProjectionModulePath = new URL("./agentMessageProcessProjection.ts", import.meta.url);
const retiredConversationProjectionModulePath = new URL("./conversationProcessProjection.ts", import.meta.url);
const timelineProjectionSource = readFileSync(
  new URL("./useAgentMessageTimelineProjection.ts", import.meta.url),
  "utf8",
);

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

describe("timeline message process projection", () => {
  it("uses the timeline process projection module as the only production DTO packet entry", () => {
    expect(existsSync(timelineProcessProjectionModulePath)).toBe(true);
    expect(existsSync(retiredAgentMessageProjectionModulePath)).toBe(false);
    expect(existsSync(retiredConversationProjectionModulePath)).toBe(false);
    expect(timelineProjectionSource).toContain("./timelineMessageProcessProjection");
    expect(timelineProjectionSource).not.toContain("./agentMessageProcessProjection");
    expect(timelineProjectionSource).not.toContain("./conversationProcessProjection");
  });

  it("uses shared special-message predicates instead of local CLI lifecycle checks", () => {
    const moduleSource = readFileSync(timelineProcessProjectionModulePath, "utf8");

    expect(moduleSource).toContain("isCliAgentLifecycleMessage");
    expect(moduleSource).toContain("./conversationMessagePredicates");
    expect(moduleSource).not.toContain("function isCliAgentLifecycleMessage");
  });

  it("merges consecutive process-only messages from the same turn while preserving each tool event", () => {
    const projected = projectTimelineProcessMessages([
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
    const projected = projectTimelineProcessMessages([
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

  it("keeps same-turn live overlay status text out of the committed assistant answer", () => {
    const projected = projectTimelineProcessMessages([
      {
        id: "message-live-overlay",
        role: "assistant",
        content: "正在唤起对话 agent...\n正在绑定 Agent 实例、私人工作区、记忆根和工具工作区。",
        timestamp: "2026-06-26T10:30:00Z",
        streaming: true,
        streamStage: "agent_prepare",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "agent_prepare",
            summary: "正在绑定 Agent",
          },
        ],
        metadata: {
          kind: "session_live_overlay",
          turnId: "turn-prepare",
        },
      },
      {
        id: "message-answer",
        role: "assistant",
        content: "你好，我可以开始处理。",
        timestamp: "2026-06-26T10:30:01Z",
        metadata: { turnId: "turn-prepare" },
      },
    ]);

    expect(projected).toHaveLength(1);
    expect(projected[0].content).toBe("你好，我可以开始处理。");
    expect(projected[0].content).not.toContain("正在唤起对话 agent");
    expect(projected[0].feedbackEvents?.map((event) => event.summary)).toEqual(["正在绑定 Agent"]);
  });

  it("merges same-turn process-only events that arrive after the assistant answer", () => {
    const projected = projectTimelineProcessMessages([
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
    const projected = projectTimelineProcessMessages([
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
    const projected = projectTimelineProcessMessages([
      toolMessage("message-tool-1", "[编辑] 成功修改 config/public_config.py", { metadata: { turnId: "turn-a" } }),
      toolMessage("message-tool-2", "[编辑] 成功修改 config/workbench.py", { metadata: { turnId: "turn-b" } }),
    ]);

    expect(projected.map((message) => message.id)).toEqual(["message-tool-1", "message-tool-2"]);
  });
});
