import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { buildConversationOperations } from "./conversationOperations";
import { buildConversationTimelineItems } from "./conversationTimeline";

const labels = {
  thought: "思考",
  mental: "心智状态",
  status: "运行状态",
};

describe("conversationTimeline", () => {
  it("keeps the complete thought stream as natural text", () => {
    const message: ConversationMessage = {
      id: "message-thought",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-06-18T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "running",
          summary: "我需要先定位会话流。\n\n然后检查前端渲染。",
          resultPreview: "我需要先定位会话流。\n\n然后检查前端渲染。",
        },
      ],
    };

    const items = buildConversationTimelineItems(
      message,
      buildConversationOperations(message, labels),
      { lang: "zh" },
    );

    expect(items[0]).toMatchObject({
      kind: "thought",
      status: "running",
      text: "我需要先定位会话流。\n\n然后检查前端渲染。",
      preview: "我需要先定位会话流。",
      defaultExpanded: true,
    });
    expect(items[1]).toMatchObject({
      kind: "assistant_text",
      text: "最终回答",
    });
  });

  it("collapses consecutive command-like tools into one readable command group", () => {
    const message: ConversationMessage = {
      id: "message-tools",
      role: "assistant",
      content: "检查完成",
      timestamp: "2026-06-18T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "搜索 conversation timeline",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "done",
          name: "read_file_tool",
          summary: "读取 ConversationView.tsx",
        },
        {
          sequence: 3,
          kind: "tool",
          status: "done",
          name: "apply_diff_edit_tool",
          summary: "编辑 1 个文件",
        },
      ],
    };

    const items = buildConversationTimelineItems(
      message,
      buildConversationOperations(message, labels),
      { lang: "zh" },
    );

    expect(items.map((item) => item.kind)).toEqual(["command_group", "operation", "assistant_text"]);
    expect(items[0]).toMatchObject({
      kind: "command_group",
      status: "completed",
      title: "已运行 2 条命令",
      summary: "搜索 conversation timeline；读取 ConversationView.tsx",
    });
    expect(items[1]).toMatchObject({
      kind: "operation",
      title: "apply_diff_edit_tool",
      summary: "编辑 1 个文件",
    });
  });

  it("does not expose mental snapshots as timeline body text", () => {
    const message: ConversationMessage = {
      id: "message-mental",
      role: "assistant",
      content: "",
      timestamp: "2026-06-18T00:00:00Z",
      mentalSnapshot: {
        mood: "focused",
        feeling: "",
        whisper: "",
        summary: "内部状态",
        cognitiveState: "productive",
        confidence: 0.9,
        sampleSize: 1,
        interventionCount: 0,
        updatedAt: "2026-06-18T00:00:00Z",
        source: "test",
      },
    };

    const items = buildConversationTimelineItems(
      message,
      buildConversationOperations(message, labels),
      { lang: "zh" },
    );

    expect(items).toEqual([]);
  });

  it("prefers backend timeline items and links them to normalized operations", () => {
    const message: ConversationMessage = {
      id: "message-server-timeline",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-06-18T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "原始搜索摘要",
        },
      ],
      timelineItems: [
        {
          id: "server-operation",
          kind: "operation",
          status: "completed",
          title: "搜索",
          summary: "后端自然摘要",
          operationIds: ["message-server-timeline-feedback-1"],
        },
        {
          id: "server-answer",
          kind: "assistant_text",
          status: "completed",
          text: "最终回答",
        },
      ],
    };

    const items = buildConversationTimelineItems(
      message,
      buildConversationOperations(message, labels),
      { lang: "zh" },
    );

    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      id: "server-operation",
      kind: "operation",
      title: "搜索",
      summary: "后端自然摘要",
    });
    expect(items[0].kind === "operation" ? items[0].operation.rawLabel : "").toBe("grep_search_tool");
    expect(items[1]).toMatchObject({
      id: "server-answer",
      kind: "assistant_text",
      text: "最终回答",
    });
  });

  it("can exclude assistant text from backend timeline items so answers render only in the answer block", () => {
    const message: ConversationMessage = {
      id: "message-server-timeline-answer",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-06-18T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "已完成分析",
        },
      ],
      timelineItems: [
        {
          id: "server-thought",
          kind: "thought",
          status: "completed",
          text: "已完成分析",
        },
        {
          id: "server-answer",
          kind: "assistant_text",
          status: "completed",
          text: "最终回答",
        },
      ],
    };

    const items = buildConversationTimelineItems(
      message,
      buildConversationOperations(message, labels),
      { lang: "zh", includeAssistantText: false },
    );

    expect(items.map((item) => item.kind)).toEqual(["thought"]);
    expect(items.map((item) => ("text" in item ? item.text : ""))).not.toContain("最终回答");
  });
});
