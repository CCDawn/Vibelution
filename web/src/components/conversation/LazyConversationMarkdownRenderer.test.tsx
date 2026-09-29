/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import styles from "./ConversationView.styles";
import rendererSource from "./LazyConversationMarkdownRenderer.tsx?raw";

// Pathological single-block fixture: only this block component crashes; the
// rest of the markdown pipeline (and every sibling block) stays healthy.
vi.mock("./conversationMarkdownMermaidBlock", () => ({
  ConversationMarkdownMermaidBlock: function BrokenMermaidBlock() {
    throw new Error("synthetic mermaid block crash");
  },
}));

describe("LazyConversationMarkdownRenderer lazy-loading contract", () => {
  it("keeps the production renderer lazy and preserves its fallback", () => {
    expect(rendererSource).toContain("const ConversationMarkdownRenderer = lazy(async () =>");
    expect(rendererSource).toContain('await import("./ConversationMarkdownRenderer")');
    expect(rendererSource).toContain(
      "<Suspense fallback={<MarkdownFallback content={props.content} classNames={props.classNames} />}>",
    );
    expect(rendererSource).not.toContain('from "./ConversationMarkdownRenderer"');
  });
});

describe("LazyConversationMarkdownRenderer fallback", () => {
  it("keeps unsafe markdown inert while the renderer chunk is still loading", () => {
    const html = renderToStaticMarkup(
      <LazyConversationMarkdownRenderer
        content={'[bad](javascript:alert(1))\n\n![bad](javascript:alert(2))'}
        classNames={styles}
      />,
    );

    expect(html).not.toMatch(/<(?:a|img)\b/i);
    expect(html).not.toMatch(/(?:href|src)=["'][^"']*javascript:/i);
  });
});

describe("LazyConversationMarkdownRenderer block-level degradation", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

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

  it("degrades one crashing block through the lazy path without triggering the message-level boundary", async () => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(
        <LazyConversationMarkdownRenderer
          content={[
            "段落甲保持正常渲染。",
            "",
            "```mermaid",
            "graph TD; A-->B;",
            "```",
            "",
            "段落乙也保持正常渲染。",
          ].join("\n")}
          classNames={styles}
        />,
      );
    });

    const html = container.innerHTML;
    // Only the sick block falls back, carrying its raw fence source.
    const blockFallback = container.querySelector<HTMLElement>('[data-markdown-block-error-fallback="true"]');
    expect(blockFallback).not.toBeNull();
    expect(blockFallback!.textContent).toContain("graph TD; A-->B;");
    // Sibling prose survives untouched through the normal markdown path.
    expect(container.textContent).toContain("段落甲保持正常渲染。");
    expect(container.textContent).toContain("段落乙也保持正常渲染。");
    // The whole-message boundary stays silent: a single bad block must not
    // take the message down to the raw-text fallback (double defense holds).
    expect(html).not.toContain("data-markdown-error-fallback");
    expect(container.textContent).not.toContain("Markdown 渲染出错，已显示原文。");
  });
});
