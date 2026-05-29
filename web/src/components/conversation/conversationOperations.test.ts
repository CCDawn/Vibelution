import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { buildConversationOperationGroups, buildConversationOperations } from "./conversationOperations";

const labels = {
  thought: "Deep thinking",
  mental: "Mental model",
};

describe("conversationOperations", () => {
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
