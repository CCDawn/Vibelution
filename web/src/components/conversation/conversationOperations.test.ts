import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import {
  buildConversationOperationGroups,
  buildConversationOperations,
  buildConversationReActOperationGroups,
} from "./conversationOperations";

const labels = {
  thought: "Deep thinking",
  mental: "Mental model",
  status: "Runtime status",
};

describe("conversationOperations", () => {
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

    const operations = buildConversationOperations(message, labels);

    expect(operations.map((item) => `${item.kind}:${item.label}:${item.summary}`)).toEqual([
      "thought:Deep thinking:先看日志",
      "tool:读取:opened latest log",
      "thought:Deep thinking:再查 React 链路",
      "tool:rg:searching feedbackEvents",
    ]);
    expect(operations[1].relatedThoughtSequence).toBe(1);
    expect(operations[3].relatedThoughtSequence).toBe(3);
  });

  it("reuses feedback operation groups until the event fingerprint changes", () => {
    const message: ConversationMessage = {
      id: "message-feedback-cache",
      role: "assistant",
      content: "Done",
      timestamp: "2026-06-05T00:00:00Z",
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "先看日志",
          resultPreview: "先看日志",
        },
      ],
    };

    const first = buildConversationOperations(message, labels);
    const second = buildConversationOperations({ ...message }, labels);
    const changed = buildConversationOperations({
      ...message,
      feedbackEvents: [
        {
          sequence: 1,
          kind: "thought",
          status: "done",
          summary: "先看最新日志",
          resultPreview: "先看最新日志",
        },
      ],
    }, labels);

    expect(second).toBe(first);
    expect(changed).not.toBe(first);
    expect(changed[0].summary).toBe("先看最新日志");
  });

  it("builds ordered assistant operations from thought, mental snapshot, and tools", () => {
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

    expect(buildConversationOperations(message, labels)).toEqual([
      {
        id: "message-1-thought",
        kind: "thought",
        label: "Deep thinking",
        status: "done",
        summary: "Check plan",
        durationSeconds: null,
        resultPreview: "Check plan",
      },
      {
        id: "message-1-mental",
        kind: "mental",
        label: "Mental model",
        status: "done",
        summary: "Need a narrow pass",
        durationSeconds: null,
      },
      {
        id: "message-1-tool-0",
        kind: "tool",
        label: "rg",
        status: "done",
        summary: "searched files",
        durationSeconds: null,
      },
      {
        id: "message-1-tool-1",
        kind: "tool",
        label: "npm run test",
        status: "running",
        summary: "",
        durationSeconds: null,
      },
    ]);
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

    const grouped = buildConversationOperationGroups(message, labels);

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

    const operations = buildConversationOperations(message, labels);
    const groups = buildConversationReActOperationGroups(operations);

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

    const groups = buildConversationReActOperationGroups(buildConversationOperations(message, labels));

    expect(groups).toHaveLength(1);
    expect(groups[0].operations.map((operation) => operation.sequence)).toEqual([1, 2]);
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

    const groups = buildConversationReActOperationGroups(buildConversationOperations(message, labels));

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

    const groups = buildConversationReActOperationGroups(buildConversationOperations(message, labels));

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

    const groups = buildConversationReActOperationGroups(buildConversationOperations(message, labels));

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

    const operations = buildConversationOperations(message, labels);

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
    const baseOperations = buildConversationOperations({
      id: "message-stable-react-group",
      role: "assistant",
      content: "",
      timestamp: "2026-06-05T00:00:00Z",
      streaming: true,
      feedbackEvents: [
        { sequence: 2, kind: "thought", status: "running", summary: "先读日志", resultPreview: "先读日志" },
        { sequence: 3, kind: "tool", status: "done", name: "read_log", summary: "opened", relatedThoughtSequence: 2 },
      ],
    }, labels);
    const withPrepStatus = buildConversationOperations({
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
    }, labels);

    expect(buildConversationReActOperationGroups(baseOperations)[0].id).toBe("react-thought-2");
    expect(buildConversationReActOperationGroups(withPrepStatus)[0].id).toBe("react-thought-2");
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

    const operations = buildConversationOperations(message, labels);

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

    const operations = buildConversationOperations(message, labels);

    expect(operations.map((item) => item.status)).toEqual(["done", "done"]);
    expect(operations[0].rawStatus).toBe("running");
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

    const operations = buildConversationOperations(message, labels);

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

    const operations = buildConversationOperations(message, labels);

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

    expect(buildConversationOperations(message, labels)).toEqual([]);
  });

  it("marks streaming thought and mental operations as running while normalizing tool details", () => {
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

    expect(buildConversationOperations(message, labels)).toEqual([
      {
        id: "message-3-thought",
        kind: "thought",
        label: "Deep thinking",
        status: "running",
        summary: "Reading files",
        durationSeconds: null,
        resultPreview: "Reading files",
      },
      {
        id: "message-3-mental",
        kind: "mental",
        label: "Mental model",
        status: "running",
        summary: "Still working",
        durationSeconds: null,
      },
      {
        id: "message-3-tool-0",
        kind: "tool",
        label: "read_file",
        status: "done",
        summary: "opened session_service.py",
        durationSeconds: 1.25,
      },
      {
        id: "message-3-tool-1",
        kind: "tool",
        label: "pytest",
        status: "running",
        summary: "focused test",
        durationSeconds: 2.5,
      },
    ]);
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

    const grouped = buildConversationOperationGroups(message, labels);

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

    const thought = buildConversationOperationGroups(message, labels).thoughts[0];

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

    expect(buildConversationOperationGroups(message, labels).mental[0]?.summary).toBe(
      "当前以规则诊断为主，认知态：稳定。",
    );
  });
});
