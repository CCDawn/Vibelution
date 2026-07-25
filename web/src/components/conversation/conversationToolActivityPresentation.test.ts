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
  it("keeps a short contiguous run as individual timeline rows", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("tool-1"),
      toolCell("tool-2"),
      toolCell("tool-3"),
    ], "zh");

    expect(items.map((item) => item.kind)).toEqual(["single", "single", "single"]);
  });

  it("folds only a long run of equivalent completed calls at its original timeline position", () => {
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
      title: "代码图谱",
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

  it("never folds failed or running tools into a completed batch", () => {
    const items = buildConversationToolActivityPresentation([
      toolCell("tool-1"),
      toolCell("tool-2"),
      toolCell("tool-3"),
      toolCell("tool-failed", { status: "failed", tone: "error" }),
      toolCell("tool-4"),
      toolCell("tool-5"),
    ], "zh");

    expect(items.map((item) => item.kind)).toEqual([
      "single",
      "single",
      "single",
      "single",
      "single",
      "single",
    ]);
    expect(items.find((item) => item.id === "tool-failed")).toMatchObject({
      kind: "single",
      cell: { status: "failed" },
    });
  });
});
