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

  it("preserves legacy tool-call raw labels while display-labeling event tool calls", () => {
    const message: AgentMessage = {
      id: "agent-tool-labels",
      role: "assistant",
      createdAt: "2026-07-02T09:20:00Z",
      streaming: true,
      source: { kind: "conversation-message", id: "agent-tool-labels" },
      parts: [
        {
          id: "agent-tool-labels-legacy",
          type: "tool-call",
          source: "legacy-tool-call",
          name: "image2_generate_tool",
          status: "failed",
          summary: "Read timed out.",
        },
        {
          id: "agent-tool-labels-feedback",
          type: "tool-call",
          source: "feedback-event",
          name: "grep_search_tool",
          status: "done",
          summary: "搜索缓存统计代码",
        },
      ],
    };

    const operations = buildAgentMessageOperations(message, labels);

    expect(operations.map((operation) => `${operation.label}:${operation.rawLabel}`)).toEqual([
      "image2_generate_tool:image2_generate_tool",
      "搜索:grep_search_tool",
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
            files: ["DEVELOPMENT_STANDARD.md", "README.md"],
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
  });

  it("prefers ordered feedback events over legacy thought and tool buckets", () => {
    const message: ConversationMessage = {
      id: "message-feedback",
      role: "assistant",
      content: "Done",
      timestamp: "2026-06-05T00:00:00Z",
      thought: "legacy latest thought",
      toolCalls: [{ name: "legacy_tool", status: "done" }],
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "先看日志",
          resultPreview: "先看日志",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "done",
          name: "read_log",
          summary: "opened latest log",
          relatedThoughtSequence: 1,
        },
        {
          sequence: 3,
          kind: "thought",
          status: "done",
          summary: "再查 React 链路",
          resultPreview: "再查 React 链路",
        },
        {
          sequence: 4,
          kind: "tool",
          status: "running",
          name: "rg",
          summary: "searching feedbackEvents",
          relatedThoughtSequence: 3,
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((item) => `${item.kind}:${item.label}:${item.summary}`)).toEqual([
      "thought:Deep thinking:先看日志",
      "tool:读取:opened latest log",
      "thought:Deep thinking:再查 React 链路",
      "tool:rg:searching feedbackEvents",
    ]);
    expect(operations[1].relatedThoughtSequence).toBe(1);
    expect(operations[3].relatedThoughtSequence).toBe(3);
  });

  it("keeps ConversationMessage operation compatibility aligned with AgentMessage projection", () => {
    const message: ConversationMessage = {
      id: "message-feedback-compat",
      role: "assistant",
      content: "Done",
      timestamp: "2026-06-05T00:00:00Z",
      thought: "fallback thought from historical payload",
      toolCalls: [{ name: "legacy_tool", status: "done", summary: "legacy tool result" }],
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型",
        },
      ],
    };

    const compatibilityOperations = operationsForConversationMessage(message);
    const agentOperations = buildAgentMessageOperations(conversationMessageToAgentMessage(message), labels);

    expect(compatibilityOperations).toEqual(agentOperations);
    expect(compatibilityOperations.map((operation) => operation.kind)).toEqual(["status", "thought", "tool"]);
  });

  it("keeps only the latest feedback update for the same unsequenced tool event", () => {
    const message: ConversationMessage = {
      id: "message-unsequenced-feedback-update",
      role: "assistant",
      content: "Done",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 0,
          kind: "tool",
          status: "running",
          name: "source_collection_context_tool",
          summary: "正在读取受控资料上下文",
        },
        {
          sequence: 0,
          kind: "tool",
          status: "done",
          name: "source_collection_context_tool",
          summary: "上下文已读取",
          resultPreview: "candidatePage.returned=19",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations).toHaveLength(1);
    expect(operations[0]).toMatchObject({
      kind: "tool",
      status: "done",
      summary: "上下文已读取",
      resultPreview: "candidatePage.returned=19",
    });
  });

  it("compacts repeated source context tools while keeping the current running tool visible", () => {
    const message: ConversationMessage = {
      id: "message-repeated-source-context-tools",
      role: "assistant",
      content: "",
      timestamp: "2026-07-06T20:19:00Z",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "done",
          name: "task_list_tool",
          summary: "| # | 描述 | 状态 | 结果摘要 | |---|---|---|---|",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "done",
          name: "task_create_tool",
          summary: "已创建 4 个任务，当前共 4 个子任务。",
        },
        ...Array.from({ length: 6 }, (_, index) => ({
          sequence: 3 + index,
          kind: "tool" as const,
          status: "done",
          name: "source_collection_context_tool",
          summary: JSON.stringify({
            candidateFieldsTruncated: true,
            candidatePage: { returned: 10 + index },
          }),
          resultPreview: JSON.stringify({
            candidateFieldsTruncated: true,
            candidatePage: { returned: 10 + index },
          }),
        })),
        {
          sequence: 9,
          kind: "tool",
          status: "running",
          name: "task_update_tool",
          summary: "运行中",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((operation) => `${operation.label}:${operation.status}:${operation.summary}`)).toEqual([
      "任务列表:done:执行完成",
      "创建任务:done:已创建 4 个任务，当前共 4 个子任务。",
      "读取资料上下文:done:执行完成",
      "更新任务:running:运行中",
    ]);
    expect(operations.filter((operation) => operation.rawLabel === "source_collection_context_tool")).toHaveLength(1);
    expect(operations.map((operation) => operation.summary).join("\n")).not.toContain("candidateFieldsTruncated");
  });

  it("normalizes completed historical operations through AgentMessage projection", () => {
    const message: ConversationMessage = {
      id: "message-1",
      role: "assistant",
      content: "Done",
      timestamp: "2026-05-22T00:00:00Z",
      thought: "Check plan",
      mentalSnapshot: {
        mood: "focused",
        feeling: "",
        whisper: "",
        summary: "Need a narrow pass",
        cognitiveState: "productive",
        confidence: 0.8,
        sampleSize: 1,
        interventionCount: 0,
        updatedAt: "2026-05-22T00:00:01Z",
        source: "test",
      },
      toolCalls: [
        { name: "rg", status: "done", summary: "searched files" },
        { name: "npm run test", status: "running" },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations).toEqual(buildAgentMessageOperations(conversationMessageToAgentMessage(message), labels));
    expect(operations).toHaveLength(4);
    expect(operations[0]).toMatchObject({
      id: "message-1-thought",
      kind: "thought",
      label: "Deep thinking",
      status: "done",
      summary: "Check plan",
      durationSeconds: null,
      resultPreview: "Check plan",
    });
    expect(operations[1]).toMatchObject({
      id: "message-1-mental",
      kind: "mental",
      label: "Mental model",
      status: "done",
      summary: "Need a narrow pass",
      durationSeconds: null,
    });
    expect(operations[2]).toMatchObject({
      id: "message-1-tool-0",
      kind: "tool",
      label: "rg",
      status: "done",
      summary: "searched files",
      durationSeconds: null,
    });
    expect(operations[3]).toMatchObject({
      id: "message-1-tool-1",
      kind: "tool",
      label: "npm run test",
      rawStatus: "running",
      status: "done",
      summary: "",
      durationSeconds: null,
    });
  });

  it("keeps runtime status feedback as a first-class timeline operation", () => {
    const message: ConversationMessage = {
      id: "message-status",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "running",
          name: "context_prepare",
          summary: "正在准备对话上下文",
        },
        {
          sequence: 2,
          kind: "status",
          status: "running",
          name: "model_request",
          summary: "正在请求模型",
        },
      ],
    };

    const grouped = operationGroupsForConversationMessage(message);

    expect(grouped.timeline.map((item) => `${item.kind}:${item.label}:${item.status}:${item.summary}`)).toEqual([
      "status:准备上下文:done:读取会话、Agent 与工具权限",
      "status:请求模型:running:首个响应片段等待中",
    ]);
    expect(grouped.timeline[1].resultPreview).toBe("正在请求模型");
    expect(grouped.status.map((item) => item.kind)).toEqual(["status", "status"]);
    expect(grouped.mental).toEqual([]);
  });

  it("splits feedback timelines into ReAct operation groups", () => {
    const message: ConversationMessage = {
      id: "message-react-groups",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        { sequence: 1, kind: "status", status: "done", name: "context_prepare", summary: "准备上下文" },
        { sequence: 2, kind: "thought", status: "done", summary: "先读代码", resultPreview: "先读代码" },
        { sequence: 3, kind: "tool", status: "done", name: "read_file_tool", summary: "opened ConversationView.tsx", relatedThoughtSequence: 2 },
        { sequence: 4, kind: "thought", status: "running", summary: "再改测试", resultPreview: "再改测试" },
        { sequence: 5, kind: "tool", status: "running", name: "cli_tool", summary: "running vitest", relatedThoughtSequence: 4 },
      ],
      streaming: true,
    };

    const operations = operationsForConversationMessage(message);
    const groups = buildAgentMessageReActOperationGroups(operations);

    expect(groups.map((group) => group.operations.map((operation) => operation.sequence))).toEqual([
      [1, 2, 3],
      [4, 5],
    ]);
    expect(groups.map((group) => group.thoughtSequence)).toEqual([2, 4]);
    expect(groups.map((group) => group.id)).toEqual(["react-thought-2", "react-thought-4"]);
  });

  it("keeps tool-only timelines in one ReAct operation group", () => {
    const message: ConversationMessage = {
      id: "message-tool-only-react-group",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        { sequence: 1, kind: "tool", status: "done", name: "cli_tool", summary: "git status" },
        { sequence: 2, kind: "tool", status: "done", name: "cli_tool", summary: "npm test" },
      ],
    };

    const groups = buildAgentMessageReActOperationGroups(operationsForConversationMessage(message));

    expect(groups).toHaveLength(1);
    expect(groups[0].operations.map((operation) => operation.sequence)).toEqual([1, 2]);
  });

  it("compacts repeated successful source writeback batches and drops superseded batch thoughts", () => {
    const message: ConversationMessage = {
      id: "message-successful-writeback-batches",
      role: "assistant",
      content: "",
      timestamp: "2026-07-03T19:54:00Z",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "继续回写第1批。",
          resultPreview: "继续回写第1批。",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "completed",
          name: "source_collection_stage_writeback_tool",
          summary: "资料提炼进行中：已完成第1批5条候选提炼",
          relatedThoughtSequence: 1,
        },
        {
          sequence: 3,
          kind: "thought",
          status: "done",
          summary: "继续回写第2批。",
          resultPreview: "继续回写第2批。",
        },
        {
          sequence: 4,
          kind: "tool",
          status: "running",
          name: "source_collection_stage_writeback_tool",
          summary: "资料提炼进行中：已完成第2批5条候选提炼",
          relatedThoughtSequence: 3,
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((operation) => `${operation.kind}:${operation.summary}`)).toEqual([
      "thought:继续回写第2批。",
      "tool:资料提炼进行中：已完成第2批5条候选提炼",
    ]);
  });

  it("starts a new ReAct packet when a tool references a different thought sequence", () => {
    const message: ConversationMessage = {
      id: "message-related-thought-split",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        { sequence: 5, kind: "tool", status: "done", name: "cli_tool", summary: "first command", relatedThoughtSequence: 4 },
        { sequence: 6, kind: "thought", status: "done", summary: "下一步", resultPreview: "下一步" },
        { sequence: 7, kind: "tool", status: "done", name: "grep_search_tool", summary: "search", relatedThoughtSequence: 6 },
      ],
    };

    const groups = buildAgentMessageReActOperationGroups(operationsForConversationMessage(message));

    expect(groups.map((group) => group.id)).toEqual(["react-thought-4", "react-thought-6"]);
    expect(groups.map((group) => group.operations.map((operation) => operation.sequence))).toEqual([
      [5],
      [6, 7],
    ]);
  });

  it("drops completed thought-only packets while keeping titled action packets", () => {
    const message: ConversationMessage = {
      id: "message-action-packet-title",
      role: "assistant",
      content: "完成。",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        { sequence: 1, kind: "thought", status: "done", summary: "先看日志", resultPreview: "先看日志" },
        { sequence: 2, kind: "tool", status: "done", name: "read_log", summary: "opened latest log", relatedThoughtSequence: 1 },
        { sequence: 3, kind: "thought", status: "done", summary: "最后整理", resultPreview: "最后整理" },
      ],
    };

    const groups = buildAgentMessageReActOperationGroups(operationsForConversationMessage(message));

    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      id: "react-thought-1",
      title: "读取",
      primaryKind: "tool",
    });
    expect(groups[0].operations.map((operation) => operation.sequence)).toEqual([1, 2]);
  });

  it("keeps running thought-only packets visible with a semantic title", () => {
    const message: ConversationMessage = {
      id: "message-running-thought-packet",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 1, kind: "thought", status: "running", summary: "正在判断下一步", resultPreview: "正在判断下一步" },
      ],
    };

    const groups = buildAgentMessageReActOperationGroups(operationsForConversationMessage(message));

    expect(groups).toHaveLength(1);
    expect(groups[0]).toMatchObject({
      title: "Deep thinking",
      primaryKind: "thought",
    });
  });

  it("merges cumulative thought prefixes from mixed LLM providers without dropping final detail", () => {
    const message: ConversationMessage = {
      id: "message-cumulative-thought",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "running",
          summary: "用户还需要修复两个问题：共享的 memory.json",
          resultPreview: "用户还需要修复两个问题：共享的 memory.json",
        },
        {
          sequence: 2,
          kind: "thought",
          status: "running",
          summary: "用户还需要修复两个问题：共享的 memory.json 文件已经严重过期",
          resultPreview: "用户还需要修复两个问题：共享的 memory.json 文件已经严重过期",
        },
        {
          sequence: 3,
          kind: "tool",
          status: "done",
          name: "grep_search_tool",
          summary: "[搜索] 正则: memory_index",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations).toHaveLength(2);
    expect(operations[0]).toMatchObject({
      kind: "thought",
      summary: "用户还需要修复两个问题：共享的 memory.json 文件已经严重过期",
      resultPreview: "用户还需要修复两个问题：共享的 memory.json 文件已经严重过期",
      status: "done",
      rawStatus: "running",
    });
    expect(operations[1]).toMatchObject({
      kind: "tool",
      label: "搜索",
      rawLabel: "grep_search_tool",
      status: "done",
    });
  });

  it("keeps ReAct group ids stable when status events are inserted before thought events", () => {
    const baseOperations = operationsForConversationMessage({
      id: "message-stable-react-group",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 2, kind: "thought", status: "running", summary: "先读日志", resultPreview: "先读日志" },
        { sequence: 3, kind: "tool", status: "done", name: "read_log", summary: "opened", relatedThoughtSequence: 2 },
      ],
    });
    const withPrepStatus = operationsForConversationMessage({
      id: "message-stable-react-group",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 1, kind: "status", status: "done", name: "context_prepare", summary: "准备上下文" },
        { sequence: 2, kind: "thought", status: "running", summary: "先读日志", resultPreview: "先读日志" },
        { sequence: 3, kind: "tool", status: "done", name: "read_log", summary: "opened", relatedThoughtSequence: 2 },
      ],
    });

    expect(buildAgentMessageReActOperationGroups(baseOperations)[0].id).toBe("react-thought-2");
    expect(buildAgentMessageReActOperationGroups(withPrepStatus)[0].id).toBe("react-thought-2");
  });

  it("keeps only the latest running operation active for legacy timelines", () => {
    const message: ConversationMessage = {
      id: "message-running-legacy",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 1, kind: "status", status: "running", name: "context_prepare", summary: "准备上下文" },
        { sequence: 2, kind: "status", status: "running", name: "agent_prepare", summary: "绑定 Agent" },
        { sequence: 3, kind: "thought", status: "running", summary: "开始思考", resultPreview: "开始思考" },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((item) => item.status)).toEqual(["done", "done", "running"]);
    expect(operations.map((item) => item.rawStatus)).toEqual(["running", "running", "running"]);
  });

  it("downgrades stale running thoughts when a later completed tool exists", () => {
    const message: ConversationMessage = {
      id: "message-stale-thought",
      role: "assistant",
      content: "完成。",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 1, kind: "thought", status: "running", summary: "我需要检查 memory.json", resultPreview: "我需要检查 memory.json" },
        { sequence: 2, kind: "tool", status: "done", name: "cli_tool", summary: "total 4" },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((item) => item.status)).toEqual(["done", "done"]);
    expect(operations[0].rawStatus).toBe("running");
  });

  it("keeps degraded returned tool feedback terminal without reporting it as normal success", () => {
    const message: ConversationMessage = {
      id: "message-degraded-tool",
      role: "assistant",
      content: "测试通过。再运行配置相关的测试验证：",
      timestamp: "2026-06-26T14:57:56Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "degraded",
          name: "cli_tool",
          summary: "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
          resultPreview: "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations).toHaveLength(1);
    expect(operations[0]).toMatchObject({
      kind: "tool",
      label: "命令",
      status: "degraded",
      rawStatus: "degraded",
      summary: "[跨平台警告] 在 Windows 上检测到 Unix shell 片段",
    });
  });

  it("preserves fallback and partial tool states instead of normalizing them to done", () => {
    const message: ConversationMessage = {
      id: "message-fallback-partial-tool",
      role: "assistant",
      content: "部分工具结果已返回。",
      timestamp: "2026-07-06T04:18:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "tool",
          status: "fallback",
          name: "cli_tool",
          summary: "使用备用结果：上游缺失 operation id",
          resultPreview: "projection gap",
        },
        {
          sequence: 2,
          kind: "tool",
          status: "partial",
          name: "read_file_tool",
          summary: "只读取到部分输出",
          resultPreview: "truncated output",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((operation) => `${operation.status}:${operation.rawStatus}:${operation.summary}`)).toEqual([
      "fallback:fallback:使用备用结果：上游缺失 operation id",
      "partial:partial:只读取到部分输出",
    ]);
  });

  it("keeps terminal synthetic thought failures neutral after a completed tool", () => {
    const message: ConversationMessage = {
      id: "message-terminal-synthetic-thought-failure",
      role: "assistant",
      content: "你好！我是 Vibelution agent，目前工作区状态正常。有什么可以帮你的吗？",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        { sequence: 1, kind: "tool", status: "done", name: "get_git_status_summary_tool", summary: "工作区干净" },
        { sequence: 2, kind: "thought", status: "failed", summary: "现在可以回应用户。", resultPreview: "现在可以回应用户。" },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((item) => `${item.kind}:${item.status}:${item.rawStatus}`)).toEqual([
      "tool:done:done",
      "thought:done:failed",
    ]);
  });

  it("keeps completed progress neutral when a final failed turn marked earlier stages failed", () => {
    const message: ConversationMessage = {
      id: "message-synthetic-failed-prefix",
      role: "assistant",
      content: "失败前已经执行过多步。",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "status",
          status: "failed",
          name: "context_prepare",
          summary: "正在准备对话上下文",
        },
        {
          sequence: 2,
          kind: "status",
          status: "failed",
          name: "agent_prepare",
          summary: "正在唤起对话 agent",
        },
        {
          sequence: 3,
          kind: "thought",
          status: "failed",
          summary: "我需要继续检查日志",
          resultPreview: "我需要继续检查日志",
        },
        {
          sequence: 4,
          kind: "tool",
          status: "done",
          name: "cli_tool",
          summary: "opened log",
        },
        {
          sequence: 5,
          kind: "tool",
          status: "failed",
          name: "cli_tool",
          summary: "[超时] cli_tool 执行超时",
          error: "[超时] cli_tool 执行超时",
        },
      ],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations.map((item) => `${item.kind}:${item.label}:${item.status}:${item.rawStatus}`)).toEqual([
      "status:准备上下文:done:failed",
      "status:绑定 Agent:done:failed",
      "thought:Deep thinking:done:failed",
      "tool:命令:done:done",
      "tool:命令:failed:failed",
    ]);
  });

  it("returns no operations for user messages", () => {
    const message: ConversationMessage = {
      id: "message-2",
      role: "user",
      content: "Hello",
      timestamp: "2026-05-22T00:00:00Z",
      toolCalls: [{ name: "ignored", status: "done" }],
    };

    expect(operationsForConversationMessage(message)).toEqual([]);
  });

  it("keeps the latest streaming historical operation running while normalizing tool details", () => {
    const message: ConversationMessage = {
      id: "message-3",
      role: "assistant",
      content: "",
      timestamp: "2026-05-22T00:00:00Z",
      streaming: true,
      thought: "Reading files",
      mentalSnapshot: {
        mood: "focused",
        feeling: "",
        whisper: "",
        summary: "Still working",
        cognitiveState: "productive",
        confidence: 0.7,
        sampleSize: 2,
        interventionCount: 0,
        updatedAt: "2026-05-22T00:00:01Z",
        source: "test",
      },
      toolCalls: [
        { name: "read_file", status: "", summary: "  opened session_service.py  ", durationMs: "1250" },
        { name: "pytest", status: "running", summary: "focused test", elapsedSeconds: 2.5 },
      ] as unknown as ConversationMessage["toolCalls"],
    };

    const operations = operationsForConversationMessage(message);

    expect(operations).toEqual(buildAgentMessageOperations(conversationMessageToAgentMessage(message), labels));
    expect(operations).toHaveLength(4);
    expect(operations[0]).toMatchObject({
      id: "message-3-thought",
      kind: "thought",
      label: "Deep thinking",
      rawStatus: "running",
      status: "done",
      summary: "Reading files",
      durationSeconds: null,
      resultPreview: "Reading files",
    });
    expect(operations[1]).toMatchObject({
      id: "message-3-mental",
      kind: "mental",
      label: "Mental model",
      rawStatus: "running",
      status: "done",
      summary: "Still working",
      durationSeconds: null,
    });
    expect(operations[2]).toMatchObject({
      id: "message-3-tool-0",
      kind: "tool",
      label: "read_file",
      status: "done",
      summary: "opened session_service.py",
      durationSeconds: 1.25,
    });
    expect(operations[3]).toMatchObject({
      id: "message-3-tool-1",
      kind: "tool",
      label: "pytest",
      rawStatus: "running",
      status: "running",
      summary: "focused test",
      durationSeconds: 2.5,
    });
  });

  it("groups thought, mental model, and tool calls separately", () => {
    const message: ConversationMessage = {
      id: "message-4",
      role: "assistant",
      content: "Done",
      timestamp: "2026-05-22T00:00:00Z",
      thought: "Plan",
      mentalSnapshot: {
        mood: "focused",
        feeling: "",
        whisper: "",
        summary: "Stable",
        cognitiveState: "productive",
        confidence: 0.8,
        sampleSize: 1,
        interventionCount: 0,
        updatedAt: "2026-05-22T00:00:01Z",
        source: "test",
      },
      toolCalls: [{ name: "rg", status: "done" }],
    };

    const grouped = operationGroupsForConversationMessage(message);

    expect(grouped.thoughts.map((item) => item.kind)).toEqual(["thought"]);
    expect(grouped.mental.map((item) => item.kind)).toEqual(["mental"]);
    expect(grouped.status).toEqual([]);
    expect(grouped.tools.map((item) => item.kind)).toEqual(["tool"]);
  });

  it("keeps captured thought text available as expandable operation detail", () => {
    const message: ConversationMessage = {
      id: "message-thought-detail",
      role: "assistant",
      content: "Done",
      timestamp: "2026-05-29T09:35:18Z",
      thought: "先看日志。\n然后确认前端有没有渲染 thought 字段。",
    };

    const thought = operationGroupsForConversationMessage(message).thoughts[0];

    expect(thought.summary).toBe("先看日志。 然后确认前端有没有渲染 thought 字段。");
    expect(thought.resultPreview).toBe("先看日志。\n然后确认前端有没有渲染 thought 字段。");
  });

  it("uses diagnosis summary when mental state details are otherwise empty", () => {
    const message: ConversationMessage = {
      id: "message-diagnosis",
      role: "assistant",
      content: "你好！我在。",
      timestamp: "2026-05-26T14:33:52",
      mentalSnapshot: {
        mood: "",
        feeling: "",
        whisper: "",
        summary: "当前以规则诊断为主，认知态：稳定。",
        cognitiveState: "normal",
        confidence: 0,
        sampleSize: 0,
        interventionCount: 0,
        updatedAt: "2026-05-26T14:33:52.789770",
        source: "diagnosis",
      },
    };

    expect(operationGroupsForConversationMessage(message).mental[0]?.summary).toBe(
      "当前以规则诊断为主，认知态：稳定。",
    );
  });
});
