// @vitest-environment happy-dom
import React, { act, type ComponentPropsWithoutRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import styles from "./ConversationView.styles";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Parse counter: every ConversationMarkdownRenderer execution creates exactly
 * one ReactMarkdown element, so wrapping the real renderer (transparently,
 * same props) counts parse passes without changing rendered output. A Profiler
 * here would be the wrong instrument: its onRender fires even when the memo
 * gate short-circuits the subtree, because the Profiler itself re-renders.
 */
const parseCalls = vi.hoisted(() => [] as number[]);

vi.mock("react-markdown", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-markdown")>();
  const RealMarkdown = actual.default;
  const CountingMarkdown = (props: ComponentPropsWithoutRef<typeof RealMarkdown>) => {
    parseCalls.push(1);
    return <RealMarkdown {...props} />;
  };
  return { default: CountingMarkdown };
});

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

  it("skips re-parsing when the content is unchanged (completed messages never re-parse)", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    parseCalls.length = 0;
    let root: Root | null = null;
    let container: HTMLElement | null = null;

    const renderWith = (content: string) => {
      act(() => {
        root!.render(
          <ConversationMarkdownRenderer content={content} classNames={styles} />,
        );
      });
    };

    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    try {
      renderWith("# stable block");
      expect(parseCalls).toHaveLength(1);

      // Parent re-render with unchanged content: the memo gate short-circuits
      // before normalize + the react-markdown AST pass, so the parse-counting
      // ReactMarkdown wrapper is never re-invoked.
      renderWith("# stable block");
      expect(parseCalls).toHaveLength(1);

      // Streaming growth re-parses exactly the changed message.
      renderWith("# stable block\nmore");
      expect(parseCalls).toHaveLength(2);
    } finally {
      act(() => {
        root?.unmount();
      });
      container.remove();
    }
  });
});
