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

  it("anchors fallback answer after process rows and keeps that slot when streaming ends", () => {
    const streamingMessage: AgentMessage = {
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
    const completedMessage: AgentMessage = {
      ...streamingMessage,
      streaming: false,
      parts: streamingMessage.parts.map((part) => (
        part.type === "tool-call" && part.status === "running"
          ? { ...part, status: "done" }
          : part.type === "thought" && part.status === "running"
            ? { ...part, status: "done" }
            : part
      )),
    };

    const streamingItems = buildAgentMessageTimelineItems(
      streamingMessage,
      buildAgentMessageOperations(streamingMessage, labels),
      { lang: "zh" },
    );
    const completedItems = buildAgentMessageTimelineItems(
      completedMessage,
      buildAgentMessageOperations(completedMessage, labels),
      { lang: "zh" },
    );

    // Process first, answer last — same relative order while streaming and after complete.
    expect(streamingItems.map((item) => item.kind)).toEqual(["thought", "operation", "operation", "assistant_text"]);
    expect(completedItems.map((item) => item.kind)).toEqual(["thought", "operation", "operation", "assistant_text"]);
    expect(streamingItems.map((item) => item.id)).toEqual(completedItems.map((item) => item.id));
    expect(streamingItems[0]).toMatchObject({
      kind: "thought",
      text: "先检查 timeline 入口",
      defaultExpanded: false,
    });
    expect(streamingItems[1]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "搜索",
      summary: "搜索 timeline 调用",
    });
    expect(streamingItems[2]).toMatchObject({
      kind: "operation",
      status: "running",
      title: "读取文件",
      summary: "读取 agentMessageTimeline.ts",
    });
    expect(streamingItems[3]).toMatchObject({
      id: "agent-message-timeline-timeline-response",
      kind: "assistant_text",
      status: "running",
      text: "正在收束 timeline 迁移",
    });
    expect(completedItems[3]).toMatchObject({
      id: "agent-message-timeline-timeline-response",
      kind: "assistant_text",
      status: "completed",
      text: "正在收束 timeline 迁移",
    });
    expect(streamingItems.filter((item) => item.kind === "assistant_text")).toHaveLength(1);
    expect(streamingItems.filter((item) => item.kind === "operation")).toHaveLength(2);
  });

  it("strictly preserves backend assistant text and operation order", () => {
    const message: AgentMessage = {
      id: "agent-message-server-timeline",
      role: "assistant",
      createdAt: "2026-07-02T10:03:00Z",
      streaming: true,
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
          id: "server-call-intro",
          kind: "assistant_text",
          status: "running",
          text: "我先检查相关配置。",
        },
        {
          id: "server-operation",
          kind: "operation",
          status: "running",
          title: "搜索",
          summary: "后端自然摘要",
          operationIds: ["agent-message-server-timeline-tool"],
        },
      ],
    );

    expect(items.map((item) => item.kind)).toEqual(["assistant_text", "operation"]);
    expect(items[0]).toMatchObject({
      id: "server-call-intro",
      kind: "assistant_text",
      status: "running",
      text: "我先检查相关配置。",
    });
    expect(items[1]).toMatchObject({
      id: "server-operation",
      kind: "operation",
      status: "running",
      title: "搜索",
      summary: "后端自然摘要",
    });
    expect(items[1].kind === "operation" ? items[1].operation.rawLabel : "").toBe("grep_search_tool");
  });

  it("keeps interleaved server order stable when tools finish", () => {
    const message: AgentMessage = {
      id: "agent-message-interleaved-timeline",
      role: "assistant",
      createdAt: "2026-07-14T23:36:41Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-message-interleaved-timeline" },
      parts: [
        {
          id: "agent-message-interleaved-tool-1",
          type: "tool-call",
          source: "feedback-event",
          name: "get_git_status_summary_tool",
          status: "running",
          summary: "检查 Git 状态",
          sequence: 2,
        },
        {
          id: "agent-message-interleaved-tool-2",
          type: "tool-call",
          source: "feedback-event",
          name: "glob_tool",
          status: "running",
          summary: "列出文件",
          sequence: 4,
        },
      ],
    };
    const serverItems = (toolStatus: "running" | "completed") => [
      { id: "intro", kind: "assistant_text", status: "completed", text: "我先检查工作区。" },
      { id: "git", kind: "operation", status: toolStatus, title: "Git 状态", operationIds: ["agent-message-interleaved-tool-1"] },
      { id: "progress", kind: "assistant_text", status: "completed", text: "工作区干净，继续检查文件。" },
      { id: "files", kind: "operation", status: toolStatus, title: "列出文件", operationIds: ["agent-message-interleaved-tool-2"] },
      { id: "answer", kind: "assistant_text", status: "completed", text: "检查完成。" },
    ];

    const runningItems = buildAgentMessageTimelineItems(
      message,
      buildAgentMessageOperations(message, labels),
      { lang: "zh" },
      serverItems("running"),
    );
    const completedItems = buildAgentMessageTimelineItems(
      { ...message, streaming: false },
      buildAgentMessageOperations({ ...message, streaming: false }, labels),
      { lang: "zh" },
      serverItems("completed"),
    );

    expect(runningItems.map((item) => item.id)).toEqual(["intro", "git", "progress", "files", "answer"]);
    expect(completedItems.map((item) => item.id)).toEqual(["intro", "git", "progress", "files", "answer"]);
  });

  it("keeps fallback completed operations before the unsplit final answer", () => {
    const message: AgentMessage = {
      id: "agent-message-completed-fallback",
      role: "assistant",
      createdAt: "2026-07-14T10:00:00Z",
      streaming: false,
      source: { kind: "conversation-message", id: "agent-message-completed-fallback" },
      parts: [
        {
          id: "agent-message-completed-fallback-tool",
          type: "tool-call",
          source: "feedback-event",
          name: "read_file_tool",
          status: "done",
          summary: "读取完成",
          sequence: 1,
        },
        {
          id: "agent-message-completed-fallback-answer",
          type: "text",
          channel: "answer",
          text: "第一段结果。\n\n第二段结论。",
        },
      ],
    };

    const items = buildAgentMessageTimelineItems(
      message,
      buildAgentMessageOperations(message, labels),
      { lang: "zh" },
    );

    expect(items.map((item) => item.kind)).toEqual(["operation", "assistant_text"]);
    expect(items[0]).toMatchObject({
      kind: "operation",
      status: "completed",
      title: "读取文件",
      summary: "读取完成",
    });
    expect(items[1]).toMatchObject({
      kind: "assistant_text",
      status: "completed",
      text: "第一段结果。\n\n第二段结论。",
    });
    expect(items.filter((item) => item.kind === "operation")).toHaveLength(1);
    expect(items.filter((item) => item.kind === "assistant_text")).toHaveLength(1);
  });});
