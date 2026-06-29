import { describe, expect, it } from "vitest";

import {
  parseStreamingMarkdownBlocks,
  projectStreamingMarkdownBlocks,
  STREAMING_MARKDOWN_LIVE_TAIL_CHARS,
} from "./streamingMarkdown";

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

  it("splits stable markdown from the live tail while preserving block output", () => {
    const stableParagraph = "稳定段落 ".repeat(80);
    const liveParagraph = "正在增长的尾部 ".repeat(80);
    const content = [
      "## 总结",
      "",
      stableParagraph,
      "",
      liveParagraph,
    ].join("\n");

    expect(content.length).toBeGreaterThan(STREAMING_MARKDOWN_LIVE_TAIL_CHARS);
    const projection = projectStreamingMarkdownBlocks(content);

    expect(projection.stableText).toContain("## 总结");
    expect(projection.liveText).toContain("正在增长的尾部");
    expect(projection.blocks).toEqual(parseStreamingMarkdownBlocks(content));
  });

  it("does not split stable markdown inside an open code fence", () => {
    const content = [
      "说明段落 ".repeat(120),
      "",
      "```ts",
      "const value = 1;",
      "console.log(value);".repeat(160),
    ].join("\n");

    const projection = projectStreamingMarkdownBlocks(content);

    expect(projection.stableText).not.toContain("```ts");
    expect(projection.blocks).toEqual(parseStreamingMarkdownBlocks(content));
  });

  it("keeps a recent table in the live tail so streamed rows do not reshape stable blocks", () => {
    const intro = "稳定上下文 ".repeat(150);
    const rows = Array.from({ length: 24 }, (_, index) => `| 指标 ${index} | ${index * 3} |`);
    const content = [
      intro,
      "",
      "| 指标 | 数值 |",
      "| --- | --- |",
      ...rows,
      "",
      "表格之后的流式总结 ".repeat(220),
    ].join("\n");

    expect(content.length).toBeGreaterThan(STREAMING_MARKDOWN_LIVE_TAIL_CHARS);
    const projection = projectStreamingMarkdownBlocks(content);

    expect(projection.stableText).not.toContain("| 指标 | 数值 |");
    expect(projection.liveText).toContain("| 指标 | 数值 |");
    expect(projection.liveBlocks[0]).toMatchObject({ type: "table" });
    expect(projection.blocks).toEqual(parseStreamingMarkdownBlocks(content));
  });
});
