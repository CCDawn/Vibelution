import { describe, expect, it } from "vitest";

import {
  CODE_BLOCK_MAX_VISIBLE_LINES,
  LIVE_CODE_MAX_VISIBLE_LINES,
  LIVE_TABLE_MAX_VISIBLE_ROWS,
  TABLE_MAX_VISIBLE_ROWS,
  countRenderableLines,
  exceedsLineBudget,
  exceedsRowBudget,
  headLines,
  headRows,
  tailLines,
} from "./conversationRenderBudget";

function linesOf(count: number, prefix = "line") {
  return Array.from({ length: count }, (_, index) => `${prefix}-${String(index + 1).padStart(3, "0")}`);
}

describe("conversationRenderBudget constants", () => {
  it("pins the staged degradation ladder thresholds", () => {
    // Completed path aligns with the ConversationPatchDiff per-file line budget.
    expect(CODE_BLOCK_MAX_VISIBLE_LINES).toBe(200);
    expect(TABLE_MAX_VISIBLE_ROWS).toBe(30);
    // Live tail renders every streaming frame, so it caps harder.
    expect(LIVE_CODE_MAX_VISIBLE_LINES).toBe(60);
    expect(LIVE_TABLE_MAX_VISIBLE_ROWS).toBe(20);
  });
});

describe("countRenderableLines / exceedsLineBudget", () => {
  it("counts literal newline-separated lines", () => {
    expect(countRenderableLines("a\nb\nc")).toBe(3);
    expect(countRenderableLines("")).toBe(1);
    expect(countRenderableLines(undefined as unknown as string)).toBe(1);
  });

  it("treats the exact budget as within budget", () => {
    expect(exceedsLineBudget("a\nb", 2)).toBe(false);
    expect(exceedsLineBudget("a\nb", 1)).toBe(true);
    // Degenerate budgets never produce zero visible lines.
    expect(exceedsLineBudget("a", 0)).toBe(false);
    expect(exceedsLineBudget("a\nb", -3)).toBe(true);
  });
});

describe("headLines", () => {
  it("returns the whole text when within budget", () => {
    const slice = headLines("a\nb\nc", 5);
    expect(slice).toEqual({ visible: "a\nb\nc", overflow: "", overflowCount: 0 });
  });

  it("keeps the head and preserves the overflow verbatim", () => {
    const allLines = linesOf(260);
    const text = [...allLines, "tail-marker"].join("\n");
    const slice = headLines(text, 200);
    expect(slice.overflowCount).toBe(61);
    expect(slice.visible).toBe(allLines.slice(0, 200).join("\n"));
    expect(slice.overflow).toBe([...allLines.slice(200), "tail-marker"].join("\n"));
    expect(slice.overflow.startsWith("line-201")).toBe(true);
  });

  it("degrades to a single visible line for degenerate budgets", () => {
    const slice = headLines("a\nb\nc", 0);
    expect(slice.visible).toBe("a");
    expect(slice.overflowCount).toBe(2);
  });
});

describe("tailLines", () => {
  it("returns the whole text when within budget", () => {
    expect(tailLines("a\nb\nc", 3)).toEqual({ visible: "a\nb\nc", overflow: "", overflowCount: 0 });
  });

  it("keeps the newest lines and counts the dropped head", () => {
    const allLines = linesOf(100);
    const text = ["head-marker", ...allLines].join("\n");
    const slice = tailLines(text, 60);
    expect(slice.overflowCount).toBe(41);
    expect(slice.visible).toBe(allLines.slice(40).join("\n"));
    expect(slice.visible.startsWith("line-041")).toBe(true);
    expect(slice.overflow).toBe(["head-marker", ...allLines.slice(0, 40)].join("\n"));
  });

  it("keeps the last line when a fence has exactly one overflow line", () => {
    const slice = tailLines("a\nb\nc", 2);
    expect(slice.visible).toBe("b\nc");
    expect(slice.overflow).toBe("a");
    expect(slice.overflowCount).toBe(1);
  });
});

describe("headRows / exceedsRowBudget", () => {
  it("keeps rows within budget untouched", () => {
    const rows = [["a"], ["b"]];
    expect(headRows(rows, 3)).toEqual({ visible: [["a"], ["b"]], overflowCount: 0 });
    expect(exceedsRowBudget(rows, 2)).toBe(false);
  });

  it("caps rows at the budget and counts the overflow", () => {
    const rows = linesOf(35).map((line) => [line]);
    const slice = headRows(rows, 30);
    expect(slice.visible).toHaveLength(30);
    expect(slice.visible[29]).toEqual(["line-030"]);
    expect(slice.overflowCount).toBe(5);
    expect(exceedsRowBudget(rows, 30)).toBe(true);
  });
});
