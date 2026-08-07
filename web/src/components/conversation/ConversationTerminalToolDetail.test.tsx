import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  buildConversationTerminalToolDetail,
  ConversationTerminalToolDetail,
} from "./ConversationTerminalToolDetail";

describe("ConversationTerminalToolDetail", () => {
  it("renders the real command separately from its output", () => {
    const command = "python -c \"p='web/src/components/conversation/ConversationToolActivity.tsx'; a=open(p,encoding='utf-8').readlines(); print(''.join(a[:360]))\"";
    const output = "import { ChevronDown, CircleAlert, LoaderCircle } from \"lucide-react\";";
    const cell: CodexTranscriptCell = {
      id: "terminal-detail",
      kind: "tool_call",
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      title: "exec_command",
      operationIds: ["terminal-operation"],
      toolLifecycleModel: {
        toolCalls: [
          {
            toolCallId: "tool-call",
            rawOperationId: "terminal-operation",
            terminalOperationId: "terminal-operation",
            status: "completed",
            title: "exec_command",
            rawToolName: "exec_command",
            runtimeKind: "terminal",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal-operation",
            rawOperationId: "terminal-operation",
            toolCallId: "tool-call",
            terminalId: "terminal-session",
            kind: "ExecCommand",
            status: "completed",
            request: { displayCommand: command },
            result: { formattedOutput: output },
          },
        ],
        terminalSessions: [],
        modelObservations: [],
      },
    };
    const detail = buildConversationTerminalToolDetail(cell, "zh");
    const html = renderToStaticMarkup(
      <ConversationTerminalToolDetail detail={detail!} language="zh" />,
    );

    expect(html).toContain(">Shell<");
    expect(html).toContain("$ python -c");
    expect(html).toContain("ConversationToolActivity.tsx");
    expect(html).toContain('aria-label="输出"');
    expect(html).toContain("ChevronDown, CircleAlert, LoaderCircle");
  });

  it("ignores polluted write_stdin display commands while preserving their output", () => {
    const pollutedOutput = "import { ChevronDown } from \"lucide-react\";";
    const cell: CodexTranscriptCell = {
      id: "terminal-write",
      kind: "tool_call",
      messageId: "message-1",
      status: "completed",
      tone: "neutral",
      title: "write_stdin",
      operationIds: ["terminal-write"],
      toolLifecycleModel: {
        toolCalls: [
          {
            toolCallId: "tool-write",
            rawOperationId: "terminal-write",
            terminalOperationId: "terminal-write",
            status: "completed",
            title: "write_stdin",
            rawToolName: "write_stdin",
            runtimeKind: "terminal",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal-write",
            rawOperationId: "terminal-write",
            toolCallId: "tool-write",
            terminalId: "terminal-session",
            kind: "WriteStdin",
            status: "completed",
            request: { displayCommand: pollutedOutput },
            result: { formattedOutput: pollutedOutput },
          },
        ],
        terminalSessions: [],
        modelObservations: [],
      },
    };

    expect(buildConversationTerminalToolDetail(cell, "zh")).toEqual({
      command: "",
      output: pollutedOutput,
      error: "",
    });
  });

  it("keeps the shell command line literal even when the tool row failed", () => {
    const cell: CodexTranscriptCell = {
      id: "terminal-failed-cmd",
      kind: "tool_call",
      messageId: "message-1",
      status: "failed",
      tone: "error",
      title: "cli_tool",
      operationIds: ["terminal-failed"],
      toolLifecycleModel: {
        toolCalls: [
          {
            toolCallId: "tool-failed",
            rawOperationId: "terminal-failed",
            terminalOperationId: "terminal-failed",
            status: "failed",
            title: "cli_tool",
            rawToolName: "cli_tool",
            runtimeKind: "terminal",
            error: "exit 1",
          },
        ],
        terminalOperations: [
          {
            operationId: "terminal-failed",
            rawOperationId: "terminal-failed",
            toolCallId: "tool-failed",
            terminalId: "terminal-session",
            kind: "ExecCommand",
            status: "failed",
            request: { displayCommand: "git status --short" },
            result: {
              formattedOutput: "M web/src/components/conversation/ConversationView.tsx",
              stderr: "exit 1",
            },
          },
        ],
        terminalSessions: [],
        modelObservations: [],
      },
    };

    expect(buildConversationTerminalToolDetail(cell, "zh")).toEqual({
      command: "git status --short",
      output: "M web/src/components/conversation/ConversationView.tsx",
      error: "exit 1",
    });
  });
});
