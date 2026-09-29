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

// Pathological block fixture: a mermaid fence whose block component crashes
// during render, simulating a hostile payload breaking exactly one block.
vi.mock("./conversationMarkdownMermaidBlock", () => ({
  ConversationMarkdownMermaidBlock: function BrokenMermaidBlock() {
    throw new Error("synthetic mermaid block crash");
  },
}));

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

  it("folds an oversized fenced code block behind an expandable disclosure", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const codeLines = Array.from({ length: 260 }, (_, index) => `代码行 ${String(index + 1).padStart(3, "0")}`);
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content={["```text", ...codeLines, "```"].join("\n")} classNames={styles} />,
    );

    // Head budget renders inline; the overflow lines stay in the DOM behind
    // the native disclosure (full semantics preserved, first paint bounded).
    expect(html).toContain("<details");
    expect(html).toContain("展开其余 60 行");
    expect(html).toContain("代码行 001");
    expect(html).toContain("代码行 200");
    expect(html).toContain("代码行 260");
    const firstPreEnd = html.indexOf("</pre>");
    expect(firstPreEnd).toBeGreaterThan(0);
    expect(html.slice(0, firstPreEnd)).not.toContain("代码行 201");
  });

  it("keeps a code block within the line budget unfolded", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const codeLines = Array.from({ length: 200 }, (_, index) => `代码行 ${String(index + 1).padStart(3, "0")}`);
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content={["```text", ...codeLines, "```"].join("\n")} classNames={styles} />,
    );

    expect(html).not.toContain("<details");
    expect(html).toContain("代码行 200");
  });

  it("renders a code block header with the lowercase language label and a text fallback", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["```Ts", "const x = 1;", "```", "", "```", "纯目录树", "```"].join("\n")}
        classNames={styles}
      />,
    );

    expect(html.match(/data-markdown-code-block="true"/g)?.length).toBe(2);
    expect(html).toMatch(/<span[^>]*markdownCodeBlockLanguage[^>]*>ts<\/span>/);
    expect(html).toMatch(/<span[^>]*markdownCodeBlockLanguage[^>]*>text<\/span>/);
    expect(html).toContain('aria-label="复制代码"');
    expect(html).toContain('aria-label="自动换行"');
    // Copy source is the rendered code text (including the fence trailing newline).
    expect(html).toContain("lucide-copy");
    expect(html).toContain("lucide-text-wrap");
  });

  it("copies the block text from the header with a Copy→Check feedback window", async () => {
    vi.useFakeTimers();
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    const prototypeDescriptor = Object.getOwnPropertyDescriptor(Navigator.prototype, "clipboard");
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      await act(async () => {
        root.render(
          <ConversationMarkdownRenderer
            content={["```python", "print('hi')", "", "print('bye')", "```"].join("\n")}
            classNames={styles}
          />,
        );
      });
      const copyButton = host.querySelector<HTMLButtonElement>('button[aria-label="复制代码"]');
      expect(copyButton).not.toBeNull();
      expect(copyButton!.querySelector("svg.lucide-copy")).not.toBeNull();
      expect(copyButton!.querySelector("svg.lucide-check")).toBeNull();

      await act(async () => {
        copyButton!.click();
      });
      expect(writeText).toHaveBeenCalledTimes(1);
      expect(writeText).toHaveBeenCalledWith("print('hi')\n\nprint('bye')\n");
      expect(copyButton!.querySelector("svg.lucide-check")).not.toBeNull();
      expect(copyButton!.querySelector("svg.lucide-copy")).toBeNull();

      // Feedback window (same duration semantics as the turn hover copy):
      // the icon reverts to Copy afterwards.
      await act(async () => {
        vi.advanceTimersByTime(1600);
      });
      expect(copyButton!.querySelector("svg.lucide-copy")).not.toBeNull();
      expect(copyButton!.querySelector("svg.lucide-check")).toBeNull();
      expect(writeText).toHaveBeenCalledTimes(1);
    } finally {
      await act(async () => {
        root.unmount();
      });
      host.remove();
      delete (navigator as { clipboard?: unknown }).clipboard;
      if (prototypeDescriptor) {
        Object.defineProperty(Navigator.prototype, "clipboard", prototypeDescriptor);
      }
      vi.useRealTimers();
    }
  });

  it("toggles soft wrap per code block from the header control", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    try {
      await act(async () => {
        root.render(
          <ConversationMarkdownRenderer
            content={["```python", "first = 1", "```", "", "```js", "second = 2", "```"].join("\n")}
            classNames={styles}
          />,
        );
      });
      const pres = host.querySelectorAll("pre");
      expect(pres.length).toBe(2);
      const wrapButton = host.querySelector<HTMLButtonElement>('button[aria-label="自动换行"]');
      expect(wrapButton).not.toBeNull();
      expect(wrapButton!.getAttribute("aria-pressed")).toBe("false");
      expect(pres[0]!.className).not.toContain("whitespace-pre-wrap");
      expect(pres[1]!.className).not.toContain("whitespace-pre-wrap");

      // Toggle affects only its own block.
      await act(async () => {
        wrapButton!.click();
      });
      expect(wrapButton!.getAttribute("aria-pressed")).toBe("true");
      expect(pres[0]!.className).toContain("whitespace-pre-wrap");
      expect(pres[1]!.className).not.toContain("whitespace-pre-wrap");

      await act(async () => {
        wrapButton!.click();
      });
      expect(wrapButton!.getAttribute("aria-pressed")).toBe("false");
      expect(pres[0]!.className).not.toContain("whitespace-pre-wrap");
    } finally {
      await act(async () => {
        root.unmount();
      });
      host.remove();
    }
  });

  it("keeps the code block header on the folded overflow path", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const codeLines = Array.from({ length: 260 }, (_, index) => `代码行 ${String(index + 1).padStart(3, "0")}`);
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content={["```text", ...codeLines, "```"].join("\n")} classNames={styles} />,
    );

    expect(html).toContain('data-markdown-code-block="true"');
    expect(html).toContain(">text<");
    expect(html).toContain("<details");
    expect(html).toContain("展开其余 60 行");
    // Header controls stay unique to the block (not duplicated per pre half).
    expect(html.match(/aria-label="复制代码"/g)?.length).toBe(1);
    expect(html.match(/aria-label="自动换行"/g)?.length).toBe(1);
  });

  it("truncates an oversized table behind an expandable disclosure", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const rows = Array.from({ length: 40 }, (_, index) => `| 行 ${String(index + 1).padStart(2, "0")} | 值 |`);
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["| 项目 | 状态 |", "| --- | --- |", ...rows].join("\n")}
        classNames={styles}
      />,
    );

    // Head rows render inline; the overflow table behind the disclosure
    // repeats the column headers so the expansion stays readable.
    expect(html).toContain("<details");
    expect(html).toContain("展开其余 10 行");
    expect(html).toContain("行 01");
    expect(html).toContain("行 40");
    const trCount = (html.match(/<tr>/g) ?? []).length;
    // thead(1) + 30 visible rows + thead(1) + 10 overflow rows.
    expect(trCount).toBe(42);
    const firstTableEnd = html.indexOf("</table>");
    expect(firstTableEnd).toBeGreaterThan(0);
    expect(html.slice(0, firstTableEnd)).not.toContain("行 31");
  });

  it("keeps a table within the row budget unfolded", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const rows = Array.from({ length: 30 }, (_, index) => `| 行 ${String(index + 1).padStart(2, "0")} | 值 |`);
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["| 项目 | 状态 |", "| --- | --- |", ...rows].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).not.toContain("<details");
    expect(html).toContain("行 30");
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

  it("keeps plaintext adjacent to leaked line-initial envelope tags visible", async () => {
    const { ConversationMarkdownRenderer, normalizeConversationMarkdown } = await import(
      "./ConversationMarkdownRenderer"
    );
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["<summary>内部摘要片段", "紧随其后的明文结论"].join("\n")}
        classNames={styles}
      />,
    );

    // The tag itself renders as literal text and no longer opens an HTML
    // block that would swallow the following plaintext up to a blank line.
    expect(html).toContain("summary");
    expect(html).toContain("内部摘要片段");
    expect(html).toContain("紧随其后的明文结论");

    const closingHtml = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["</summary>", "</think>紧随闭合标签的明文"].join("\n")}
        classNames={styles}
      />,
    );
    expect(closingHtml).toContain("紧随闭合标签的明文");

    // Escaping is idempotent across repeated normalize passes (streaming
    // re-normalizes the whole content on every frame).
    const once = normalizeConversationMarkdown("<summary>片段\n明文");
    expect(normalizeConversationMarkdown(once)).toBe(once);
    expect(once).toContain("\\<summary>");
  });

  it("does not escape envelope tags inside fenced code blocks", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["```text", "<summary>代码示例原文", "```"].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain("&lt;summary&gt;代码示例原文");
    expect(html).not.toContain("\\<");
  });

  it("renders default-path markdown images lazily and async-decoded", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["![截图](https://example.com/screen.png)", "![bad](javascript:alert(1))"].join("\n\n")}
        classNames={styles}
      />,
    );

    expect(html).toMatch(/<img[^>]*loading="lazy"/);
    expect(html).toMatch(/<img[^>]*decoding="async"/);
    expect(html).toContain('src="https://example.com/screen.png"');
    expect(html).toContain('alt="截图"');
    // Unsafe schemes never reach the DOM even on the default image path.
    expect(html).not.toContain("javascript:");
    expect((html.match(/<img/g) ?? []).length).toBe(1);
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

  it("renders single-dollar inline math and $$ block math through KaTeX", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    // Block math is the flow form ($$ on its own lines) — remark-math only
    // marks that as display; a single-line `$$…$$` stays inline.
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer
        content={["边际成本 $c = a + b$ 递增。", "", "$$", "\\sum_{i=1}^{n} x_i", "$$"].join("\n")}
        classNames={styles}
      />,
    );

    expect(html).toContain('class="katex"');
    expect(html).toContain("katex-display");
    expect(html).toContain("边际成本");
    expect(html).toContain("递增");
  });

  it("keeps dollar amounts as literal text instead of formulas", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content="套餐价格 $5-$10，月费 $100，年费 $1,200。" classNames={styles} />,
    );

    expect(html).not.toContain("katex");
    expect(html).toContain("$5-$10");
    expect(html).toContain("$100");
    expect(html).toContain("$1,200");
  });

  it("degrades a failed formula to its LaTeX source without breaking the message", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content="前文 $\notacommand$ 后文继续。" classNames={styles} />,
    );

    // KaTeX's throwOnError:false fallback keeps the raw source visible in the
    // muted error color (rehype-katex degrades instead of throwing), and the
    // surrounding prose survives untouched.
    expect(html).toContain("notacommand");
    expect(html).toContain("color:var(--fg-tertiary)");
    expect(html).toContain("前文");
    expect(html).toContain("后文继续");
  });

  it("leaves a lone dollar sign as plain text without crashing", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content="成本合计约 $ 元。" classNames={styles} />,
    );

    expect(html).not.toContain("katex");
    expect(html).toContain("成本合计约 $ 元。");
  });

  it("skips the math pipeline inside fenced code blocks", async () => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    const html = renderToStaticMarkup(
      <ConversationMarkdownRenderer content={["```bash", "export PRICE=$5-$10", "echo $PATH", "```"].join("\n")} classNames={styles} />,
    );

    expect(html).not.toContain("katex");
    expect(html).toContain("export PRICE=$5-$10");
    expect(html).toContain("echo $PATH");
  });
});

describe("ConversationMarkdownRenderer block-level degradation", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  const renderWith = async (content: string) => {
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(<ConversationMarkdownRenderer content={content} classNames={styles} />);
    });
  };

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  it("degrades only the crashing block to raw text and keeps sibling blocks rendering", async () => {
    await renderWith(
      [
        "段落甲保持正常渲染。",
        "",
        "```mermaid",
        "graph TD; A-->B;",
        "```",
        "",
        "段落乙也保持正常渲染。",
      ].join("\n"),
    );

    const html = container!.innerHTML;
    // The sick block degrades into the block-level fallback carrying its raw
    // fence source, styled with the host pre chrome like its healthy siblings.
    const blockFallback = container!.querySelector<HTMLElement>('[data-markdown-block-error-fallback="true"]');
    expect(blockFallback).not.toBeNull();
    expect(blockFallback!.textContent).toContain("graph TD; A-->B;");
    const fallbackPre = blockFallback!.querySelector("pre");
    expect(fallbackPre?.className).toContain("responseSegmentPre");
    // The mermaid block itself never mounted.
    expect(html).not.toContain("data-markdown-mermaid-block");
    // Sibling prose renders through the normal markdown path.
    expect(container!.textContent).toContain("段落甲保持正常渲染。");
    expect(container!.textContent).toContain("段落乙也保持正常渲染。");
    expect(container!.querySelectorAll("p").length).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain("data-markdown-error-fallback");
  });

  it("keeps the degraded block stable across an unchanged re-render and retries on content change", async () => {
    await renderWith(["```mermaid", "graph TD; A-->B;", "```"].join("\n"));
    expect(container!.querySelector('[data-markdown-block-error-fallback="true"]')).not.toBeNull();
    expect(container!.textContent).toContain("graph TD; A-->B;");

    // Unchanged content re-render: stays degraded with the same source, no
    // state churn (idempotent fallback).
    const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
    await act(async () => {
      root!.render(
        <ConversationMarkdownRenderer content={["```mermaid", "graph TD; A-->B;", "```"].join("\n")} classNames={styles} />,
      );
    });
    expect(container!.querySelector('[data-markdown-block-error-fallback="true"]')).not.toBeNull();
    expect(container!.textContent).toContain("graph TD; A-->B;");

    // Content change under the failed block: the boundary retries once and
    // degrades again — showing the NEW raw text, not a stale copy.
    await act(async () => {
      root!.render(
        <ConversationMarkdownRenderer content={["```mermaid", "graph TD; X-->Y;", "```"].join("\n")} classNames={styles} />,
      );
    });
    expect(container!.querySelector('[data-markdown-block-error-fallback="true"]')).not.toBeNull();
    expect(container!.textContent).toContain("graph TD; X-->Y;");
    expect(container!.textContent).not.toContain("graph TD; A-->B;");
  });

  it("extracts block source text and stable keys from the hast node", async () => {
    const { markdownBlockBoundaryKey, markdownBlockSourceText } = await import(
      "./conversationMarkdownBlockBoundary"
    );
    const tableNode = {
      type: "element",
      tagName: "table",
      position: { start: { line: 3, column: 1 } },
      children: [
        {
          type: "element",
          tagName: "thead",
          children: [
            {
              type: "element",
              tagName: "tr",
              children: [
                { type: "element", tagName: "th", children: [{ type: "text", value: "项目" }] },
                { type: "element", tagName: "th", children: [{ type: "text", value: "状态" }] },
              ],
            },
          ],
        },
        {
          type: "element",
          tagName: "tbody",
          children: [
            {
              type: "element",
              tagName: "tr",
              children: [
                { type: "element", tagName: "td", children: [{ type: "text", value: "A" }] },
                { type: "element", tagName: "td", children: [{ type: "text", value: "ok" }] },
              ],
            },
          ],
        },
      ],
    };

    // Rows separate by newline, cells by two spaces, code-style whitespace
    // preserved elsewhere; malformed input degrades to "" instead of throwing.
    expect(markdownBlockSourceText(tableNode)).toBe("项目  状态\nA  ok");
    expect(markdownBlockSourceText({ type: "element", tagName: "pre", children: [{ type: "text", value: "a\nb" }] })).toBe(
      "a\nb",
    );
    expect(markdownBlockSourceText(undefined)).toBe("");
    expect(markdownBlockBoundaryKey(tableNode)).toBe("md-block-3:1");
    expect(markdownBlockBoundaryKey({ type: "text", value: "x" })).toBeUndefined();
  });
});
