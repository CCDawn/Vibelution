import { describe, expect, it } from "vitest";

import type { AgentMessageOperation } from "./agentMessageOperations";
import codexRolloutTraceSource from "./codexRolloutTrace.ts?raw";
import {
  buildCodexRolloutTraceEvents,
  type CodexRolloutTraceEvent,
  type CodexRolloutTraceEventKind,
} from "./codexRolloutTrace";

function toolOperation(overrides: Partial<AgentMessageOperation> = {}): AgentMessageOperation {
  return {
    id: "op-tool",
    kind: "tool",
    label: "搜索",
    rawLabel: "web_search_tool",
    status: "done",
    summary: "搜索 ConversationView",
    durationSeconds: null,
    ...overrides,
  };
}

describe("codexRolloutTrace", () => {
  it("exports a Codex-like rollout trace event contract", () => {
    const kind: CodexRolloutTraceEventKind = "RuntimeEnded";
    const event: CodexRolloutTraceEvent = {
      id: "op-tool-runtime-ended",
      kind,
      operationId: "op-tool",
      status: "completed",
      title: "搜索",
      runtimeKind: "tool",
    };

    expect(event.kind).toBe("RuntimeEnded");
    expect(codexRolloutTraceSource).toContain("export type CodexRolloutTraceEventKind");
    expect(codexRolloutTraceSource).toContain("export type CodexRolloutTraceEvent =");
    expect(codexRolloutTraceSource).toContain("export function buildCodexRolloutTraceEvents");
  });

  it("projects a completed tool operation into the four Codex rollout lifecycle events", () => {
    const events = buildCodexRolloutTraceEvents(toolOperation({
      id: "op-search",
      sequence: 7,
      timestamp: "2026-07-06T16:10:00Z",
    }));

    expect(events.map((event) => event.kind)).toEqual([
      "ToolCallStarted",
      "RuntimeStarted",
      "RuntimeEnded",
      "ToolCallEnded",
    ]);
    expect(events[0]).toMatchObject({
      id: "op-search-tool-call-started",
      kind: "ToolCallStarted",
      operationId: "op-search",
      status: "running",
      runtimeKind: "tool",
      rawToolName: "web_search_tool",
      sequence: 7,
      timestamp: "2026-07-06T16:10:00Z",
    });
    expect(events[2]).toMatchObject({
      id: "op-search-runtime-ended",
      kind: "RuntimeEnded",
      operationId: "op-search",
      status: "completed",
      runtimeKind: "tool",
    });
    expect(events[3]).toMatchObject({
      id: "op-search-tool-call-ended",
      kind: "ToolCallEnded",
      status: "completed",
    });
  });

  it("keeps terminal failure diagnostics on runtime end events", () => {
    const failedCommand = {
      ...toolOperation({
        id: "op-command",
        label: "命令",
        rawLabel: "cli_tool",
        status: "failed",
        summary: "npm test",
        error: "Exit code 1",
        durationSeconds: 2.5,
        tracePath: "logs/runtime_scenes/run-1/timeline.jsonl",
      }),
      exitCode: 1,
      timedOut: true,
    } satisfies AgentMessageOperation & { exitCode: number; timedOut: boolean };

    const events = buildCodexRolloutTraceEvents(failedCommand);

    expect(events.map((event) => event.kind)).toEqual([
      "ToolCallStarted",
      "RuntimeStarted",
      "RuntimeEnded",
      "ToolCallEnded",
    ]);
    expect(events[2]).toMatchObject({
      kind: "RuntimeEnded",
      operationId: "op-command",
      status: "failed",
      runtimeKind: "terminal",
      error: "Exit code 1",
      durationSeconds: 2.5,
      tracePath: "logs/runtime_scenes/run-1/timeline.jsonl",
      exitCode: 1,
      timedOut: true,
    });
  });

  it("does not invent end events while a tool operation is still running", () => {
    const events = buildCodexRolloutTraceEvents(toolOperation({
      id: "op-running",
      status: "running",
      summary: "等待工具输出",
    }));

    expect(events.map((event) => event.kind)).toEqual([
      "ToolCallStarted",
      "RuntimeStarted",
    ]);
    expect(events.every((event) => event.status === "running")).toBe(true);
  });

  it("keeps degraded tool lifecycles degraded instead of completed", () => {
    const events = buildCodexRolloutTraceEvents(toolOperation({
      id: "op-partial",
      status: "partial",
      summary: "只返回部分输出",
    }));

    expect(events.map((event) => event.kind)).toEqual([
      "ToolCallStarted",
      "RuntimeStarted",
      "RuntimeEnded",
      "ToolCallEnded",
    ]);
    expect(events[2]).toMatchObject({
      kind: "RuntimeEnded",
      status: "degraded",
      summary: "只返回部分输出",
    });
    expect(events[3]).toMatchObject({
      kind: "ToolCallEnded",
      status: "degraded",
    });
  });

  it("does not project thoughts, mental notes, or status rows as full tool calls", () => {
    const events = buildCodexRolloutTraceEvents([
      {
        id: "op-thought",
        kind: "thought",
        label: "思考",
        status: "done",
        summary: "先分析",
        durationSeconds: null,
      },
      {
        id: "op-mental",
        kind: "mental",
        label: "心理状态",
        status: "done",
        summary: "聚焦",
        durationSeconds: null,
      },
      {
        id: "op-status",
        kind: "status",
        label: "准备上下文",
        status: "running",
        summary: "读取当前会话",
        durationSeconds: null,
      },
    ]);

    expect(events).toEqual([]);
  });
});
