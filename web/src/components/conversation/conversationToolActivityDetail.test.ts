import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import {
  buildConversationToolActivityDetailRows,
  parseToolFailureHint,
} from "./conversationToolActivityDetail";

function failedWebFetch(summary: string): CodexTranscriptCell {
  return {
    id: "web-1",
    kind: "error_notice",
    messageId: "message-1",
    status: "failed",
    tone: "error",
    title: "web_fetch_tool",
    summary,
    operationIds: ["op-1"],
    diagnosticSummary: {
      reasonCode: "tool_failed",
      reasonSummary: summary,
    },
    toolLifecycleModel: {
      toolCalls: [
        {
          toolCallId: "call-1",
          rawOperationId: "op-1",
          status: "failed",
          title: "web_fetch_tool",
          rawToolName: "web_fetch_tool",
          runtimeKind: "tool",
          error: summary,
        },
      ],
      terminalOperations: [],
      terminalSessions: [],
      modelObservations: [],
    },
  };
}

describe("conversationToolActivityDetail", () => {
  it("splits an HTTP 406 one-liner into URL and status without repeating the subject", () => {
    const summary = "HTTP 406: https://elifesciences.org/articles/13810";
    expect(parseToolFailureHint(summary)).toEqual({
      status: "406",
      url: "https://elifesciences.org/articles/13810",
    });

    const rows = buildConversationToolActivityDetailRows(failedWebFetch(summary), "zh");
    expect(rows).toEqual([
      { label: "URL", value: "https://elifesciences.org/articles/13810" },
      { label: "状态", value: "406" },
    ]);
    expect(rows.map((row) => row.value).join(" ")).not.toContain("HTTP 406: https://");
  });

  it("keeps a distinct error body when it is not the same as the visible one-liner", () => {
    const cell = failedWebFetch("HTTP 406: https://example.com/a");
    cell.diagnosticSummary = {
      reasonCode: "fetch_rejected",
      reasonSummary: "HTTP 406: https://example.com/a",
      reasonDetail: "站点拒绝当前 Accept 头",
    };
    const rows = buildConversationToolActivityDetailRows(cell, "zh");
    expect(rows).toContainEqual({ label: "URL", value: "https://example.com/a" });
    expect(rows).toContainEqual({ label: "状态", value: "406" });
    expect(rows).toContainEqual({ label: "详情", value: "站点拒绝当前 Accept 头" });
    expect(rows).toContainEqual({ label: "代码", value: "fetch_rejected" });
  });
});
