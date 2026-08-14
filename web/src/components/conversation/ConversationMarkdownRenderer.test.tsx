import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import styles from "./ConversationView.styles";

describe("ConversationMarkdownRenderer", () => {
  it("normalizes common agent markdown glitches into readable blocks", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={[
          "关键假设：自进化主 Agent正在按 SPEC 推进。",
          "-无法验证最近 3 次 launcher 运行。",
          "- 无法验证 web/目录的样式收敛。",
          "1.读取 logs/runtime_scenes/<包路径>/summary.json",
          "2.执行 git diff--stat 与 pytest 映射。",
        ].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain("markdownBody");
    expect(html).toContain("<strong");
    expect(html).toContain("关键假设");
    expect(html).toMatch(/<strong[^>]*>关键假设<\/strong>：自进化主 Agent/);
    expect(html).toContain("<ul");
    expect(html).toContain("<ol");
    expect(html).toContain("<li");
    expect(html).toContain("无法验证最近 3 次 launcher 运行");
    expect(html).toContain("读取 logs/runtime_scenes");
  });

  it("does not mistake bold text for a missing-space list item", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content="**我当前使用的模型档案 `primary` 不支持图像输入。**"
        classNames={styles}
      />,
    );

    expect(html).toContain("inlineStrong");
    expect(html).toContain("inlineCode");
    expect(html).toContain("primary");
    expect(html).not.toContain("<ul");
    expect(html).not.toContain("<em>");
  });

  it("renders GFM tables and task lists without relying on browser defaults", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={[
          "| 项目 | 状态 |",
          "| --- | --- |",
          "| Markdown | ready |",
          "",
          "- [x] 表格",
          "- [ ] 视觉回归",
        ].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain("markdownBodyWithTable");
    expect(html).toContain("<table");
    expect(html).toContain("<thead");
    expect(html).toContain("<tbody");
    expect(html).toContain('type="checkbox"');
    expect(html).toContain("checked");
    expect(html).toContain("table-auto");
    expect(html).toContain("overflow-x-auto");
    expect(html).toContain("list-disc");
  });

  it("keeps ordered and unordered lists visually distinct", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={[
          "- first",
          "- second",
          "",
          "1. one",
          "2. two",
        ].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toMatch(/<ul[^>]*list-disc/);
    expect(html).toMatch(/<ol[^>]*list-decimal/);
  });

  it("preserves unlabeled fenced directory trees as block code", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={[
          "```",
          "项目根",
          "├─ agent.py                   216 KB",
          "└─ core/",
          "   └─ web/",
          "```",
        ].join("\n")}
        classNames={styles}
      />,
    );

    const blockStart = html.indexOf("<pre");
    const blockEnd = html.indexOf("</pre>", blockStart);
    const blockHtml = html.slice(blockStart, blockEnd);
    expect(blockStart).toBeGreaterThanOrEqual(0);
    expect(blockHtml).toContain("responseSegmentPre");
    expect(blockHtml).toContain("项目根\n├─ agent.py                   216 KB");
    expect(blockHtml).not.toContain("inlineCode");
  });

  it("keeps labeled fenced code formatting in the block renderer", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["```json", '{"status":"ok"}', "```"].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain('class="language-json"');
    expect(html).toContain("{\n  &quot;status&quot;: &quot;ok&quot;\n}");
    expect(html).not.toContain("inlineCode");
  });

  it("keeps unsafe markdown inert while allowing safe links", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={[
          "[safe](/api/sessions/s1/artifacts/a.png)",
          "[bad](javascript:alert(1))",
          "<script>alert(1)</script>",
        ].join("\n\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain('href="/api/sessions/s1/artifacts/a.png"');
    expect(html).toContain("safe");
    expect(html).toContain("bad");
    expect(html).not.toContain("javascript:");
    expect(html).not.toContain("<script");
    expect(html).not.toContain("alert(1)");
  });
});
