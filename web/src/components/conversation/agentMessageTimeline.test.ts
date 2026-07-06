import { describe, expect, it } from "vitest";
import { existsSync } from "node:fs";

import { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread";
import { buildAgentMessageOperations } from "./agentMessageOperations";
import agentMessageTimelineSource from "./agentMessageTimeline.ts?raw";
import { buildAgentMessageTimelineItems, type AgentMessageTimelineOptions } from "./agentMessageTimeline";

const labels = {
  thought: "思考",
  mental: "心智状态",
  status: "运行状态",
};

function timelineItemsForConversationMessage(
  message: ConversationMessage,
  options: AgentMessageTimelineOptions,
) {
  const agentMessage = conversationMessageToAgentMessage(message);
  return buildAgentMessageTimelineItems(
    agentMessage,
    buildAgentMessageOperations(agentMessage, labels),
    options,
    message.timelineItems,
  );
}

describe("agentMessageTimeline", () => {
  it("keeps the AgentMessage timeline module on AgentMessage-named files", () => {
    expect(existsSync(new URL("./agentMessageTimeline.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./conversationTimeline.ts", import.meta.url))).toBe(false);
  });

  it("names timeline item contracts after the AgentMessage timeline model", () => {
    expect(agentMessageTimelineSource).toContain("export type AgentMessageTimelineItemStatus");
    expect(agentMessageTimelineSource).toContain("export type AgentMessageTimelineItem =");
    expect(agentMessageTimelineSource).toContain("export type AgentMessageTimelineOptions");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationTimelineItemStatus");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationThoughtTimelineItem");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationAssistantTextTimelineItem");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationCommandGroupTimelineItem");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationTimelineItem =");
    expect(agentMessageTimelineSource).not.toContain("export type ConversationTimelineOptions");
  });

  it("names operation timeline items after the AgentMessage operation model", () => {
    expect(agentMessageTimelineSource).toContain("AgentMessageOperationTimelineItem");
    expect(agentMessageTimelineSource).not.toContain("ConversationOperationTimelineItem");
  });

  it("keeps the AgentMessage timeline model decoupled from API timeline DTO imports", () => {
    expect(agentMessageTimelineSource).toContain("export type AgentMessageTimelineServerItem");
    expect(agentMessageTimelineSource).not.toContain("../../api/types");
    expect(agentMessageTimelineSource).not.toContain("ApiConversationTimelineItem");
    expect(agentMessageTimelineSource).not.toContain("ConversationTimelineItem as");
  });

  it("builds timeline items from AgentMessage parts", () => {
    const message: AgentMessage = {
      id: "agent-message-timeline",
      role: "assistant",
      createdAt: "2026-07-02T10:00:00Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-message-timeline" },
      parts: [
        {
          id: "agent-message-timeline-thought",
          type: "thought",
          status: "running",
          text: "先检查 timeline 入口",
          sequence: 1,
        },
        {
          id: "agent-message-timeline-search",
          type: "tool-call",
          source: "feedback-event",
          name: "grep_search_tool",
          status: "done",
          summary: "搜索 timeline 调用",
          sequence: 2,
        },
        {
          id: "agent-message-timeline-read",
          type: "tool-call",
          source: "feedback-event",
          name: "read_file_tool",
          status: "running",
          summary: "读取 agentMessageTimeline.ts",
          sequence: 3,
        },
        {
          id: "agent-message-timeline-answer",
          type: "text",
          channel: "answer",
          text: "正在收束 timeline 迁移",
        },
      ],
    };

    const items = buildAgentMessageTimelineItems(
      message,
      buildAgentMessageOperations(message, labels),
      { lang: "zh" },
    );

    expect(items.map((item) => item.kind)).toEqual(["thought", "operation", "operation", "assistant_text"]);
    expect(items[0]).toMatchObject({
      kind: "thought",
      text: "先检查 timeline 入口",
      defaultExpanded: false,
    });
    expect(items[1]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "搜索",
      summary: "搜索 timeline 调用",
    });
    expect(items[2]).toMatchObject({
      kind: "operation",
      status: "running",
      title: "读取文件",
      summary: "读取 agentMessageTimeline.ts",
    });
    expect(items[3]).toMatchObject({
      kind: "assistant_text",
      status: "running",
      text: "正在收束 timeline 迁移",
    });
  });

  it("keeps backend timeline items when building from AgentMessage parts", () => {
    const message: AgentMessage = {
      id: "agent-message-server-timeline",
      role: "assistant",
      createdAt: "2026-07-02T10:03:00Z",
      streaming: false,
      source: { kind: "conversation-message", id: "agent-message-server-timeline" },
      parts: [
        {
          id: "agent-message-server-timeline-tool",
          type: "tool-call",
          source: "feedback-event",
          name: "grep_search_tool",
          status: "done",
          summary: "原始搜索摘要",
          sequence: 1,
        },
        {
          id: "agent-message-server-timeline-answer",
          type: "text",
          channel: "answer",
          text: "最终回答",
        },
      ],
    };

    const items = buildAgentMessageTimelineItems(
      message,
      buildAgentMessageOperations(message, labels),
      { lang: "zh" },
      [
        {
          id: "server-operation",
          kind: "operation",
          status: "completed",
          title: "搜索",
          summary: "后端自然摘要",
          operationIds: ["agent-message-server-timeline-tool"],
        },
      ],
    );

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      id: "server-operation",
      kind: "operation",
      title: "搜索",
      summary: "后端自然摘要",
    });
    expect(items[0].kind === "operation" ? items[0].operation.rawLabel : "").toBe("grep_search_tool");
  });

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

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

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

  it("renders consecutive command-like tools as individual timeline rows", () => {
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

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

    expect(items.map((item) => item.kind)).toEqual(["operation", "operation", "operation", "assistant_text"]);
    expect(items[0]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "搜索",
      summary: "搜索 conversation timeline",
    });
    expect(items[1]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "读取文件",
      summary: "读取 ConversationView.tsx",
    });
    expect(items[2]).toMatchObject({
      kind: "operation",
      status: "completed",
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

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

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

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

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

  it("expands backend command groups into individual operation timeline rows", () => {
    const message: ConversationMessage = {
      id: "message-server-command-group",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-06-18T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "搜索配置文件",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "error",
          name: "cli_tool",
          summary: "命令执行失败",
        },
      ],
      timelineItems: [
        {
          id: "server-command-group",
          kind: "command_group",
          status: "failed",
          title: "已运行 2 条命令",
          summary: "搜索配置文件；命令执行失败",
          operationIds: [
            "message-server-command-group-feedback-1",
            "message-server-command-group-feedback-2",
          ],
        },
        {
          id: "server-answer",
          kind: "assistant_text",
          status: "completed",
          text: "最终回答",
        },
      ],
    };

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

    expect(items.map((item) => item.kind)).toEqual(["operation", "operation", "assistant_text"]);
    expect(items[0]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "搜索",
      summary: "搜索配置文件",
    });
    expect(items[1]).toMatchObject({
      kind: "operation",
      status: "failed",
      title: "命令",
      summary: "命令执行失败",
    });
    expect(items).not.toContainEqual(expect.objectContaining({
      kind: "command_group",
      title: "已运行 2 条命令",
    }));
  });

  it("expands command groups whose server operation ids use the persisted message id prefix", () => {
    const message: ConversationMessage = {
      id: "session-live-message-253",
      role: "assistant",
      content: "本轮已按请求停止。",
      timestamp: "2026-07-05T23:32:43",
      feedbackEvents: [
        {
          sequence: 9,
          kind: "tool",
          status: "failed",
          name: "grep_search_tool",
          summary: "参数不符合当前工具签名",
        },
        {
          sequence: 10,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "搜索完成",
        },
      ],
      timelineItems: [
        {
          id: "session-live-message-253-timeline-command-group-9-10",
          kind: "command_group",
          status: "failed",
          title: "已运行 2 条命令",
          summary: "参数错误；搜索完成",
          operationIds: [
            "session-live-message-253-feedback-9",
            "session-live-message-253-feedback-10",
          ],
        },
      ],
    };

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

    expect(items.map((item) => item.kind)).toEqual(["operation", "operation"]);
    expect(items.map((item) => ("title" in item ? item.title : ""))).toEqual(["搜索", "搜索"]);
    expect(items).not.toContainEqual(expect.objectContaining({
      kind: "command_group",
      title: "已运行 2 条命令",
    }));
  });

  it("surfaces command group projection gaps instead of silently rendering aggregate command rows", () => {
    const message: ConversationMessage = {
      id: "message-missing-command-ops",
      role: "assistant",
      content: "最终回答",
      timestamp: "2026-06-18T00:00:00Z",
      feedbackEvents: [],
      timelineItems: [
        {
          id: "server-command-group-missing",
          kind: "command_group",
          status: "failed",
          title: "已运行 2 条命令",
          summary: "搜索配置文件；命令执行失败",
          operationIds: [
            "missing-feedback-1",
            "missing-feedback-2",
          ],
        },
      ],
    };

    const items = timelineItemsForConversationMessage(message, { lang: "zh" });

    expect(items).toEqual([
      expect.objectContaining({
        kind: "operation",
        status: "failed",
        title: "工具调用投影缺失",
        summary: "server-command-group-missing 引用了 2 条工具结果，但当前消息没有匹配的 operation 投影。",
      }),
    ]);
    expect(items).not.toContainEqual(expect.objectContaining({
      kind: "command_group",
      title: "已运行 2 条命令",
    }));
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

    const items = timelineItemsForConversationMessage(message, { lang: "zh", includeAssistantText: false });

    expect(items.map((item) => item.kind)).toEqual(["thought"]);
    expect(items.map((item) => ("text" in item ? item.text : ""))).not.toContain("最终回答");
  });
});
