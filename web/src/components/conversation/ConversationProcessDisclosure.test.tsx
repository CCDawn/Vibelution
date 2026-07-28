import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";
import styles from "./ConversationProcessDisclosure.styles";
import type { CodexTranscriptCell } from "./codexTranscriptCells";

function processCell(status: CodexTranscriptCell["status"]): CodexTranscriptCell {
  return {
    id: `process-${status}`,
    kind: "tool_call",
    messageId: "message-1",
    status,
    tone: status === "running" ? "running" : "neutral",
    title: "cli_tool",
    toolLifecycleModel: {
      toolCalls: [],
      terminalOperations: [
        {
          operationId: "terminal-1",
          rawOperationId: "operation-1",
          toolCallId: "tool-call-1",
          terminalId: "terminal-1",
          kind: "ExecCommand",
          status,
          durationSeconds: 2.9,
        },
      ],
      terminalSessions: [],
      modelObservations: [],
    },
  };
}

describe("ConversationProcessDisclosure", () => {
  it("renders a completed process collapsed with only its state and duration", () => {
    const html = renderToStaticMarkup(
      <ConversationProcessDisclosure cells={[processCell("completed")]} language="zh">
        <span>处理记录内容</span>
      </ConversationProcessDisclosure>,
    );

    expect(html).toContain('data-codex-process-disclosure="true"');
    expect(html).not.toContain('open=""');
    expect(html).toContain("已处理 2.9s");
    expect(html).not.toContain("个阶段");
    expect(html).toContain("处理记录内容");
    expect(styles.summary).not.toContain("border-b");
    expect(styles.content).toContain("border-l");
  });

  it("opens and announces only an active process without exposing per-item progress metadata", () => {
    const html = renderToStaticMarkup(
      <ConversationProcessDisclosure cells={[processCell("running")]} language="zh">
        <span>正在执行</span>
      </ConversationProcessDisclosure>,
    );

    expect(html).toContain("处理中 2.9s");
    expect(html).not.toContain("个阶段");
    expect(html).toContain('open=""');
    expect(html).toContain('aria-live="polite"');
    expect(html).not.toContain("1 次调用");
  });

  it("keeps a stopped process collapsed with an explicit failure summary", () => {
    const html = renderToStaticMarkup(
      <ConversationProcessDisclosure cells={[processCell("failed")]} language="en">
        <span>Stopped process details</span>
      </ConversationProcessDisclosure>,
    );

    expect(html).toContain("Processing stopped 2.9s");
    expect(html).not.toContain("stage");
    expect(html).toContain('data-codex-process-state="failed"');
    expect(html).not.toContain('open=""');
  });
});
