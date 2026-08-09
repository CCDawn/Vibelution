import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread/adapters";
import type { AgentMessage } from "../../agent-thread";
import * as agentMessageOperationsModule from "./agentMessageOperations";
import agentMessageTimelineSource from "./agentMessageTimeline.ts?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import agentMessageOperationsSource from "./agentMessageOperations.ts?raw";
import {
  buildAgentMessageOperationGroups,
  buildAgentMessageOperations,
  buildAgentMessageReActOperationGroups,
} from "./agentMessageOperations";

const labels = {
  thought: "Deep thinking",
  mental: "Mental model",
  status: "Runtime status",
};

function operationsForConversationMessage(message: ConversationMessage) {
  return buildAgentMessageOperations(conversationMessageToAgentMessage(message), labels);
}

function operationGroupsForConversationMessage(message: ConversationMessage) {
  return buildAgentMessageOperationGroups(conversationMessageToAgentMessage(message), labels);
}

describe("agentMessageOperations", () => {
  it("uses the AgentMessage operation module path as the only production entry", () => {
    expect(existsSync(new URL("./agentMessageOperations.ts", import.meta.url))).toBe(true);
    expect(existsSync(new URL("./conversationOperations.ts", import.meta.url))).toBe(false);
    expect(agentMessageTimelineSource).toContain("./agentMessageOperations");
    expect(conversationViewSource).toContain("./agentMessageOperations");
    expect(agentMessageTimelineSource).not.toContain("./conversationOperations");
    expect(conversationViewSource).not.toContain("./conversationOperations");
  });

  it("keeps display normalization helpers internal to the operation model", () => {
    expect("normalizeTimelineOperations" in agentMessageOperationsModule).toBe(false);
    expect("displayToolLabel" in agentMessageOperationsModule).toBe(false);
  });

  it("exports ReAct grouping through AgentMessage naming only", () => {
    expect("buildAgentMessageReActOperationGroups" in agentMessageOperationsModule).toBe(true);
    expect("buildConversationReActOperationGroups" in agentMessageOperationsModule).toBe(false);
    expect(agentMessageOperationsSource).toContain("AgentMessageReActOperationGroup");
    expect(agentMessageOperationsSource).not.toContain("ConversationReActOperationGroup");
  });

  it("exports operation model types through AgentMessage naming only", () => {
    expect(agentMessageOperationsSource).toContain("export type AgentMessageOperationKind");
    expect(agentMessageOperationsSource).toContain("export type AgentMessageOperation =");
    expect(agentMessageOperationsSource).toContain("export type AgentMessageOperationLabels");
    expect(agentMessageOperationsSource).toContain("export type AgentMessageOperationGroups");
    expect(agentMessageOperationsSource).not.toContain("export type ConversationOperationKind");
    expect(agentMessageOperationsSource).not.toContain("export type ConversationOperation =");
    expect(agentMessageOperationsSource).not.toContain("export type ConversationOperationLabels");
    expect(agentMessageOperationsSource).not.toContain("export type ConversationOperationGroups");
  });

  it("keeps the AgentMessage operation model decoupled from the conversation DTO", () => {
    expect(agentMessageOperationsSource).not.toContain("../../api/types");
    expect(agentMessageOperationsSource).not.toContain("ConversationFeedbackEvent");
  });

  it("builds operation groups from AgentMessage parts", () => {
    const message: AgentMessage = {
      id: "agent-message-parts",
      role: "assistant",
      createdAt: "2026-07-02T09:10:00Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-message-parts" },
      parts: [
        {
          id: "agent-message-parts-status",
          type: "runtime-event",
          kind: "status",
          name: "model_request",
          status: "running",
          summary: "正在请求模型",
        },
        {
          id: "agent-message-parts-thought",
          type: "thought",
          status: "running",
          text: "检查 AgentMessage parts",
          sequence: 2,
        },
        {
          id: "agent-message-parts-tool",
          type: "tool-call",
          name: "read_file_tool",
          status: "done",
          summary: "读取 ConversationView",
          resultPreview: "export function ConversationView",
          arguments: { path: "ConversationView.tsx" },
          durationMs: 1200,
          relatedThoughtSequence: 2,
        },
        {
          id: "agent-message-parts-text",
          type: "text",
          channel: "answer",
          text: "回答正文不应进入 operation timeline",
        },
      ],
    };

    const operations = buildAgentMessageOperations(message, labels);
    const grouped = buildAgentMessageOperationGroups(message, labels);

    expect(operations.map((operation) => `${operation.kind}:${operation.label}:${operation.summary}`)).toEqual([
      "status:请求模型:首个响应片段等待中",
      "thought:Deep thinking:检查 AgentMessage parts",
      "tool:读取文件:读取 ConversationView",
    ]);
    expect(grouped.status).toHaveLength(1);
    expect(grouped.thoughts).toHaveLength(1);
    expect(grouped.tools[0]).toMatchObject({
      id: "agent-message-parts-tool",
      rawLabel: "read_file_tool",
      arguments: { path: "ConversationView.tsx" },
      durationSeconds: 1.2,
      relatedThoughtSequence: 2,
      resultPreview: "export function ConversationView",
    });
  });

  it("display-labels feedback-event tool calls without a legacy source escape hatch", () => {
    const message: AgentMessage = {
      id: "agent-tool-labels",
      role: "assistant",
      createdAt: "2026-07-02T09:20:00Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-tool-labels" },
      parts: [
        {
          id: "agent-tool-labels-feedback-search",
          type: "tool-call",
          source: "feedback-event",
          name: "grep_search_tool",
          status: "done",
          summary: "搜索缓存统计代码",
        },
        {
          id: "agent-tool-labels-feedback-image",
          type: "tool-call",
          source: "feedback-event",
          name: "image2_generate_tool",
          status: "failed",
          summary: "Read timed out.",
        },
      ],
    };

    const operations = buildAgentMessageOperations(message, labels);

    expect(operations.map((operation) => `${operation.label}:${operation.rawLabel}`)).toEqual([
      "搜索:grep_search_tool",
      "生成图片:image2_generate_tool",
    ]);
  });

  it("maps code search and raw tool identifiers to readable labels", () => {
    const message: AgentMessage = {
      id: "agent-tool-readable-labels",
      role: "assistant",
      createdAt: "2026-07-07T06:50:00Z",
      streaming: false,
      source: { kind: "conversation-message", id: "agent-tool-readable-labels" },
      parts: [
        {
          id: "agent-tool-readable-labels-read",
          type: "tool-call",
          source: "feedback-event",
          name: "read_file_tool",
          status: "done",
          summary: "opened latest package",
        },
        {
          id: "agent-tool-readable-labels-search",
          type: "tool-call",
          source: "feedback-event",
          name: "search_code_tool",
          status: "done",
          summary: "searched session detail",
        },
        {
          id: "agent-tool-readable-labels-rg",
          type: "tool-call",
          source: "feedback-event",
          name: "rg",
          status: "done",
          summary: "searched session detail",
        },
      ],
    };

    const operations = buildAgentMessageOperations(message, labels);

    expect(operations.map((operation) => operation.label)).toEqual([
      "读取文件",
      "搜索代码",
      "搜索",
    ]);
    expect(operations.map((operation) => operation.rawLabel)).toEqual([
      "read_file_tool",
      "search_code_tool",
      "rg",
    ]);
  });

  it("keeps raw tool payloads out of main timeline summaries while preserving details", () => {
    const message: AgentMessage = {
      id: "agent-tool-summary-noise",
      role: "assistant",
      createdAt: "2026-07-05T23:12:00Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-tool-summary-noise" },
      parts: [
        {
          id: "agent-tool-summary-git",
          type: "tool-call",
          source: "feedback-event",
          name: "get_git_status_summary_tool",
          status: "done",
          summary: JSON.stringify({
            dirty_summary: "有 unstaged 改动，有 untracked 文件，共 17 个变化文件",
          }),
          resultPreview: JSON.stringify({
            dirty_summary: "有 unstaged 改动，有 untracked 文件，共 17 个变化文件",
            files: ["docs/standards/development-standard.md", "README.md"],
          }),
        },
        {
          id: "agent-tool-summary-code",
          type: "tool-call",
          source: "feedback-event",
          name: "code_symbol_tool",
          status: "failed",
          summary: JSON.stringify({ status: "error", reason: "parse failed" }),
          resultPreview: "749- if len(self._thought_history) > self._thought_history_max:\n750- self._thought_history =",
        },
      ],
    };

    const operations = buildAgentMessageOperations(message, labels);

    expect(operations[0]).toMatchObject({
      label: "Git 状态",
      summary: "有 unstaged 改动，有 untracked 文件，共 17 个变化文件",
      resultPreview: expect.stringContaining("dirty_summary"),
    });
    expect(operations[1]).toMatchObject({
      label: "代码图谱",
      status: "failed",
      summary: "执行失败",
      resultPreview: expect.stringContaining("749- if len"),
    });
    expect(operations.map((operation) => operation.summary).join("\n")).not.toContain("{");
    expect(operations.map((operation) => operation.summary).join("\n")).not.toContain("self._thought_history");
  });it("returns no operations for user messages", () => {
    const message: ConversationMessage = {
      id: "message-2",
      role: "user",
      content: "Hello",
      timestamp: "2026-05-22T00:00:00Z",
      toolCalls: [{ name: "ignored", status: "done" }],
    };

    expect(operationsForConversationMessage(message)).toEqual([]);
  });});

describe("projected cli tool semantic labels", () => {
  it("uses command semantics for the projected operation label and keeps the protocol name diagnostic", () => {
    const message: AgentMessage = {
      id: "projected-cli-label",
      role: "assistant",
      createdAt: "2026-07-14T08:00:00Z",
      streaming: false,
      source: { kind: "conversation-message", id: "projected-cli-label" },
      parts: [
        {
          id: "projected-cli-status",
          type: "tool-call",
          name: "cli_tool",
          status: "done",
          summary: "检查工作区",
          arguments: { command: "git status --short --branch" },
        },
      ],
    };

    expect(buildAgentMessageOperations(message, labels)[0]).toMatchObject({
      label: "检查 Git 状态",
      rawLabel: "cli_tool",
    });
  });
});
