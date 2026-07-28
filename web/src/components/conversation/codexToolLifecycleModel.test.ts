import { describe, expect, it } from "vitest";

import type { AgentMessageOperation } from "./agentMessageOperations";
import codexToolLifecycleModelSource from "./codexToolLifecycleModel.ts?raw";
import {
  buildCodexToolLifecycleModel,
  type CodexTerminalOperation,
  type CodexToolLifecycleModel,
} from "./codexToolLifecycleModel";

function toolOperation(overrides: Partial<AgentMessageOperation> = {}): AgentMessageOperation {
  return {
    id: "op-tool",
    kind: "tool",
    label: "命令",
    rawLabel: "cli_tool",
    status: "done",
    summary: "npm --prefix web run test",
    durationSeconds: 1.5,
    tracePath: "logs/runtime_scenes/run-1/timeline.jsonl",
    ...overrides,
  };
}

describe("codexToolLifecycleModel", () => {
  it("exports a Codex-like tool lifecycle model contract", () => {
    const terminalOperation: CodexTerminalOperation = {
      operationId: "terminal_operation:0",
      toolCallId: "tool_call:op-tool",
      terminalId: "terminal:op-tool",
      kind: "ExecCommand",
      status: "completed",
      request: {
        displayCommand: "npm --prefix web run test",
        cwd: "",
      },
      result: {
        formattedOutput: "ok",
      },
      rawOperationId: "op-tool",
    };
    const model: CodexToolLifecycleModel = {
      toolCalls: [],
      terminalOperations: [terminalOperation],
      terminalSessions: [],
      modelObservations: [],
    };

    expect(model.terminalOperations[0].kind).toBe("ExecCommand");
    expect(codexToolLifecycleModelSource).toContain("export type CodexToolLifecycleModel");
    expect(codexToolLifecycleModelSource).toContain("export type CodexTerminalOperation");
    expect(codexToolLifecycleModelSource).toContain("export function buildCodexToolLifecycleModel");
  });

  it("reduces a completed terminal-like operation into tool call, terminal operation, session, and observation records", () => {
    const model = buildCodexToolLifecycleModel(toolOperation({
      id: "op-command",
      terminalSessionId: "terminal-command",
      sequence: 12,
      timestamp: "2026-07-07T10:00:00Z",
      error: "",
    }));

    expect(model.toolCalls).toEqual([
      expect.objectContaining({
        toolCallId: "tool_call:op-command",
        rawOperationId: "op-command",
        status: "completed",
        rawToolName: "cli_tool",
        runtimeKind: "terminal",
        terminalOperationId: "terminal_operation:0",
      }),
    ]);
    expect(model.terminalOperations).toEqual([
      expect.objectContaining({
        operationId: "terminal_operation:0",
        terminalId: "terminal:terminal-command",
        toolCallId: "tool_call:op-command",
        kind: "ExecCommand",
        status: "completed",
        rawOperationId: "op-command",
        request: expect.objectContaining({
          displayCommand: "npm --prefix web run test",
        }),
        result: expect.objectContaining({
          formattedOutput: "npm --prefix web run test",
        }),
      }),
    ]);
    expect(model.terminalSessions).toEqual([
      expect.objectContaining({
        terminalId: "terminal:terminal-command",
        operationIds: ["terminal_operation:0"],
        status: "completed",
      }),
    ]);
    expect(model.modelObservations).toEqual([
      expect.objectContaining({
        operationId: "terminal_operation:0",
        toolCallId: "tool_call:op-command",
        source: "DirectToolCall",
      }),
    ]);
  });

  it("keeps non-terminal tools as tool call records without inventing terminal sessions", () => {
    const model = buildCodexToolLifecycleModel(toolOperation({
      id: "op-search",
      label: "搜索",
      rawLabel: "web_search_tool",
      summary: "搜索 Codex streaming",
    }));

    expect(model.toolCalls[0]).toMatchObject({
      toolCallId: "tool_call:op-search",
      runtimeKind: "tool",
    });
    expect(model.toolCalls[0]).not.toHaveProperty("terminalOperationId");
    expect(model.terminalOperations).toEqual([]);
    expect(model.terminalSessions).toEqual([]);
    expect(model.modelObservations).toEqual([]);
  });

  it("does not invent a terminal session from a command-like label or summary", () => {
    const model = buildCodexToolLifecycleModel(toolOperation({
      id: "op-command-like",
      rawLabel: "cli_tool",
      label: "命令",
      summary: "powershell npm --prefix web run test",
    }));

    expect(model.toolCalls[0]).toMatchObject({
      runtimeKind: "terminal",
    });
    expect(model.toolCalls[0]).not.toHaveProperty("terminalOperationId");
    expect(model.terminalOperations).toEqual([]);
    expect(model.terminalSessions).toEqual([]);
  });

  it("preserves failed terminal diagnostics in terminal results", () => {
    const failedCommand = {
      ...toolOperation({
        id: "op-failed",
        terminalSessionId: "terminal-failed",
        status: "failed",
        summary: "npm test",
        error: "Exit code 1",
        durationSeconds: 2.25,
      }),
      exitCode: 1,
      timedOut: true,
    } satisfies AgentMessageOperation & { exitCode: number; timedOut: boolean };

    const model = buildCodexToolLifecycleModel(failedCommand);

    expect(model.toolCalls[0]).toMatchObject({
      status: "failed",
      terminalOperationId: "terminal_operation:0",
    });
    expect(model.terminalOperations[0]).toMatchObject({
      status: "failed",
      durationSeconds: 2.25,
      result: {
        exitCode: 1,
        timedOut: true,
        formattedOutput: "Exit code 1",
        stderr: "Exit code 1",
      },
    });
    expect(model.terminalSessions[0]).toMatchObject({
      status: "failed",
      operationIds: ["terminal_operation:0"],
    });
  });

  it("aggregates terminal operations that share a runtime session key", () => {
    const model = buildCodexToolLifecycleModel([
      toolOperation({
        id: "op-exec",
        rawLabel: "cli_tool",
        summary: "npm run dev",
        status: "done",
        arguments: { session_id: "terminal-a" },
      }),
      toolOperation({
        id: "op-stdin",
        rawLabel: "write_stdin",
        summary: "q",
        status: "running",
        arguments: { session_id: "terminal-a" },
      }),
    ]);

    expect(model.terminalOperations).toEqual([
      expect.objectContaining({
        operationId: "terminal_operation:0",
        terminalId: "terminal:terminal-a",
        kind: "ExecCommand",
        status: "completed",
      }),
      expect.objectContaining({
        operationId: "terminal_operation:1",
        terminalId: "terminal:terminal-a",
        kind: "WriteStdin",
        status: "running",
        request: expect.not.objectContaining({
          displayCommand: expect.anything(),
        }),
      }),
    ]);
    expect(model.terminalSessions).toEqual([
      expect.objectContaining({
        terminalId: "terminal:terminal-a",
        createdByOperationId: "terminal_operation:0",
        operationIds: ["terminal_operation:0", "terminal_operation:1"],
        status: "running",
      }),
    ]);
  });

  it("does not reduce thoughts, mental notes, or status rows as Codex tool calls", () => {
    const model = buildCodexToolLifecycleModel([
      {
        id: "op-thought",
        kind: "thought",
        label: "思考",
        status: "done",
        summary: "先看上下文",
        durationSeconds: null,
      },
      {
        id: "op-status",
        kind: "status",
        label: "请求模型",
        status: "running",
        summary: "等待首个响应片段",
        durationSeconds: null,
      },
    ]);

    expect(model).toEqual({
      toolCalls: [],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    });
  });
});
