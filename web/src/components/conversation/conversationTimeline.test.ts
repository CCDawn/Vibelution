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
});
