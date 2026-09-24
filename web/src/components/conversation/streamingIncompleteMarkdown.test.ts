import { describe, expect, it } from "vitest";

import { parseStreamingMarkdownBlocks } from "./streamingMarkdown";
import { repairIncompleteMarkdown } from "./streamingIncompleteMarkdown";

describe("repairIncompleteMarkdown (streaming live-tail light parse)", () => {
  it("closes an unterminated code fence so the block stays a code block", () => {
    const { repaired, stats } = repairIncompleteMarkdown("```python\nprint(1)");
    expect(stats.closedFence).toBe(true);
    const blocks = parseStreamingMarkdownBlocks(repaired);
    expect(blocks.at(-1)).toMatchObject({ type: "code", language: "python", open: false });
  });

  it("leaves balanced fences untouched", () => {
    const source = "```js\nconst a = 1;\n```\n之后";
    const { repaired, stats } = repairIncompleteMarkdown(source);
    expect(stats.closedFence).toBe(false);
    expect(repaired).toBe(source);
  });

  it("completes a header-only table with a separator row", () => {
    const { repaired, stats } = repairIncompleteMarkdown("| A | B |");
    expect(stats.completedTable).toBe(true);
    const blocks = parseStreamingMarkdownBlocks(repaired);
    expect(blocks[0]).toMatchObject({ type: "table", headers: ["A", "B"] });
    expect(blocks[0]?.type === "table" && blocks[0].rows).toHaveLength(0);
  });

  it("keeps a complete table untouched", () => {
    const source = "| A | B |\n| --- | --- |\n| 1 | 2 |";
    const { repaired, stats } = repairIncompleteMarkdown(source);
    expect(stats.completedTable).toBe(false);
    expect(repaired).toBe(source);
  });

  it("balances odd emphasis marks and inline backticks outside fences", () => {
    const { repaired, stats } = repairIncompleteMarkdown("加粗到一半**黑体 和 `代码");
    expect(stats.balancedMarks).toBeGreaterThanOrEqual(2);
    // Innermost span closes first: bold opened before the code tick, so the
    // code tick closes before the bold marker.
    expect(repaired.endsWith("`代码`**")).toBe(true);
  });

  it("never balances marks inside a fence body", () => {
    const source = "```text\n**未配对 * 星号\n```";
    const { repaired } = repairIncompleteMarkdown(source);
    expect(repaired.startsWith(source)).toBe(true);
  });

  it("is deterministic and newline-normalizing", () => {
    const source = "| A |\r\n| 1";
    expect(repairIncompleteMarkdown(source)).toEqual(repairIncompleteMarkdown(source));
    const { repaired } = repairIncompleteMarkdown(source);
    expect(repaired).not.toContain("\r");
  });
});
