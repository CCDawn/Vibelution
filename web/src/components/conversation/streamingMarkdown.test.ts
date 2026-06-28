import { describe, expect, it } from "vitest";

import { parseStreamingMarkdownBlocks } from "./streamingMarkdown";

describe("parseStreamingMarkdownBlocks", () => {
  it("keeps open code fences as code blocks while streaming", () => {
    const blocks = parseStreamingMarkdownBlocks([
      "## 实时标题",
      "",
      "```ts",
      "const value = 1;",
    ].join("\n"));

    expect(blocks).toEqual([
      { type: "heading", level: 2, content: "实时标题" },
      { type: "code", language: "ts", content: "const value = 1;", open: true },
    ]);
  });

  it("renders a table as soon as the header and separator are available", () => {
    const blocks = parseStreamingMarkdownBlocks([
      "| 指标 | 数值 |",
      "| --- | --- |",
      "| 缓存 | 98%",
    ].join("\n"));

    expect(blocks).toEqual([
      {
        type: "table",
        headers: ["指标", "数值"],
        rows: [["缓存", "98%"]],
      },
    ]);
  });
});
