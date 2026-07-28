import { describe, expect, it } from "vitest";

import type { CodexTranscriptCell } from "./codexTranscriptCells";
import { buildConversationToolActivityPresentation } from "./conversationToolActivityPresentation";

function toolCell(
  id: string,
  options: Partial<Pick<CodexTranscriptCell, "status" | "tone" | "title">> = {},
): CodexTranscriptCell {
  return {
    id,
    kind: "tool_call",
    messageId: "message-1",
    status: "completed",
    tone: "neutral",
    title: "code_symbol_tool",
    ...options,
  };
}

describe("buildConversationToolActivityPresentation", () => {
  it("folds a short contiguous semantic family into one work stage", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("tool-1"),
      toolCell("tool-2", { title: "semantic_graph_tool" }),
      toolCell("tool-3"),
    ], "zh");

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "batch",
      title: "代码分析",
      count: 3,
    });
  });

  it("folds a completed semantic stage at its original timeline position", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("tool-1"),
      toolCell("tool-2"),
      toolCell("tool-3"),
      toolCell("tool-4"),
      toolCell("search-1", { title: "grep_search_tool" }),
    ], "zh");

    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({
      kind: "batch",
      title: "代码分析",
      count: 4,
    });
    expect(items[0]?.kind === "batch" ? items[0].cells.map((cell) => cell.id) : []).toEqual([
      "tool-1",
      "tool-2",
      "tool-3",
      "tool-4",
    ]);
    expect(items[1]).toMatchObject({ kind: "single", id: "search-1" });
  });

  it("keeps failed tools visible while folding successful stages on each side", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("tool-1"),
      toolCell("tool-2"),
      toolCell("tool-3"),
      toolCell("tool-failed", { status: "failed", tone: "error" }),
      toolCell("tool-4"),
      toolCell("tool-5"),
    ], "zh");

    expect(items.map((item) => item.kind)).toEqual(["batch", "single", "batch"]);
    expect(items.find((item) => item.id === "tool-failed")).toMatchObject({
      kind: "single",
      cell: { status: "failed" },
    });
  });

  it("uses distinct edit and verification stages instead of a generic tool bucket", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("edit-1", { title: "apply_patch_tool" }),
      toolCell("edit-2", { title: "apply_diff_edit_tool" }),
      toolCell("verify-1", { title: "python_lint_tool" }),
      toolCell("verify-2", { title: "run_test_for_tool" }),
    ], "zh");

    expect(items).toMatchObject([
      { kind: "batch", title: "修改文件", count: 2 },
      { kind: "batch", title: "验证", count: 2 },
    ]);
  });
});
