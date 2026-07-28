import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { buildCodexTranscriptTimelineNodes } from "./conversationToolActivityModel";

function cell(id: string, kind: CodexTranscriptCell["kind"], status: CodexTranscriptCell["status"] = "completed"): CodexTranscriptCell {
  return {
    id,
    kind,
    messageId: "message-1",
    status,
    tone: status === "failed" ? "error" : "neutral",
    title: kind === "tool_call" ? "code_symbol_tool" : undefined,
    text: kind === "assistant_markdown" ? id : undefined,
  };
}

describe("conversation tool activity model", () => {
  it("groups only contiguous non-terminal tool calls and preserves canonical order around commentary", () => {
    const nodes = buildCodexTranscriptTimelineNodes([
      cell("commentary-before", "assistant_markdown"),
      cell("tool-1", "tool_call"),
      cell("tool-2", "tool_call"),
      cell("tool-3", "tool_call"),
      cell("commentary-after", "assistant_markdown"),
      cell("tool-4", "tool_call"),
      cell("final", "assistant_markdown"),
    ]);

    expect(nodes.map((node) => node.kind === "cell" ? node.cell.id : node.activity.id)).toEqual([
      "commentary-before",
      "tool-activity:tool-1",
      "commentary-after",
      "tool-activity:tool-4",
      "final",
    ]);
    expect(nodes[1]).toMatchObject({
      kind: "tool_activity",
      activity: { cells: [{ id: "tool-1" }, { id: "tool-2" }, { id: "tool-3" }] },
    });
  });

  it("keeps contiguous completed, failed, and degraded tool work in one activity", () => {
    const failedTool = cell("tool-failed", "error_notice", "failed");
    failedTool.operationIds = ["operation-failed"];
    const nodes = buildCodexTranscriptTimelineNodes([
      cell("tool-1", "tool_call"),
      failedTool,
      cell("tool-2", "tool_call"),
      cell("tool-degraded", "tool_call", "degraded"),
    ]);

    expect(nodes).toHaveLength(1);
    expect(nodes[0]).toMatchObject({
      kind: "tool_activity",
      activity: {
        cells: [
          { id: "tool-1" },
          { id: "tool-failed" },
          { id: "tool-2" },
          { id: "tool-degraded" },
        ],
      },
    });
  });

  it("keeps a non-operation error notice as a narrative barrier", () => {
    const nodes = buildCodexTranscriptTimelineNodes([
      cell("tool-1", "tool_call"),
      cell("turn-error", "error_notice", "failed"),
      cell("tool-2", "tool_call"),
    ]);

    expect(nodes.map((node) => node.kind === "cell" ? node.cell.id : node.activity.id)).toEqual([
      "tool-activity:tool-1",
      "turn-error",
      "tool-activity:tool-2",
    ]);
  });
});
