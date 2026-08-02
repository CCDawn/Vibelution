import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ConversationProcessDisclosure,
  processLabel,
  processState,
} from "./ConversationProcessDisclosure";
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
    // SSR keeps canonical transcript evidence inspectable; the browser client
    // lazily mounts this subtree only after an explicit expansion.
    expect(html).toContain("处理记录内容");
    expect(html).toContain('data-codex-process-expanded="false"');
    expect(styles.summary).toContain("w-full");
    expect(styles.summary).toContain("border-b");
    expect(styles.summary).toContain("[font-size:var(--vui-font-sm)]");
    expect(styles.content).not.toContain("border-l");
    expect(styles.content).not.toContain("ml-");
    expect(styles.content).not.toContain("pl-");
    expect(styles.contentMotion).toContain("transition-[grid-template-rows,opacity]");
    expect(styles.contentMotion).toContain("motion-reduce:transition-none");
    expect(styles.contentMotion).toContain("[overflow-anchor:none]");
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
    expect(html).toContain('data-codex-process-expanded="true"');
    expect(html).toContain('aria-live="polite"');
    expect(html).not.toContain("1 次调用");
    expect(html).toContain("正在执行");
  });

  it("keeps a failed process collapsed with tool failure summary", () => {
    const html = renderToStaticMarkup(
      <ConversationProcessDisclosure cells={[processCell("failed")]} language="en">
        <span>Stopped process details</span>
      </ConversationProcessDisclosure>,
    );

    expect(html).toContain("Tool failed 2.9s");
    expect(html).toContain("cli_tool");
    expect(html).not.toContain("stage");
    expect(html).toContain('data-codex-process-state="failed"');
    expect(html).not.toContain('open=""');
  });

  it("labels Chinese tool failures without implying the whole session stopped", () => {
    const html = renderToStaticMarkup(
      <ConversationProcessDisclosure cells={[processCell("failed")]} language="zh">
        <span>失败细节</span>
      </ConversationProcessDisclosure>,
    );
    expect(html).toContain("工具失败");
    expect(html).not.toContain("处理已停止");
  });

  it("keeps failure details in the expanded transcript instead of duplicating them in the summary", () => {
    const failed = {
      ...processCell("failed"),
      summary: "终端会话已结束，不能继续写入。",
    };

    const label = processLabel([failed], "zh");

    expect(label).toContain("工具失败");
    expect(label).toContain("cli_tool");
    expect(label).not.toContain(failed.summary);
  });

  it("marks a failed tool call as recovered when the same tool succeeds later", () => {
    const failed = {
      ...processCell("failed"),
      id: "writeback-failed",
      title: "challenge_cup_iteration_writeback_tool",
    };
    const recovered = {
      ...processCell("completed"),
      id: "writeback-recovered",
      title: "challenge_cup_iteration_writeback_tool",
    };

    expect(processState([failed, recovered])).toBe("completed");
    expect(processLabel([failed, recovered], "zh")).toContain("已处理");
    expect(processLabel([failed, recovered], "zh")).not.toContain("工具失败");
  });

  it("uses canonical message order when compacted cells place an older failure last", () => {
    const olderFailure = {
      ...processCell("failed"),
      id: "writeback-failed",
      messageId: "assistant-message-35",
      title: "challenge_cup_iteration_writeback_tool",
    };
    const laterSuccess = {
      ...processCell("completed"),
      id: "writeback-recovered",
      messageId: "assistant-message-37",
      title: "challenge_cup_iteration_writeback_tool",
    };
    const messageOrder = new Map([
      ["assistant-message-35", 0],
      ["assistant-message-37", 1],
    ]);

    expect(processState([laterSuccess, olderFailure], messageOrder)).toBe("completed");
    expect(processLabel([laterSuccess, olderFailure], "zh", messageOrder)).toContain("已处理");
  });

  it("keeps a failure visible when only another tool succeeds later", () => {
    const failed = {
      ...processCell("failed"),
      id: "writeback-failed",
      title: "challenge_cup_iteration_writeback_tool",
    };
    const otherTool = {
      ...processCell("completed"),
      id: "context-completed",
      title: "challenge_cup_iteration_context_tool",
    };

    expect(processState([failed, otherTool])).toBe("failed");
    expect(processLabel([failed, otherTool], "zh")).toContain("工具失败");
    expect(processLabel([failed, otherTool], "zh")).toContain(
      "challenge_cup_iteration_writeback_tool",
    );
  });
});
