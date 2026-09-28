/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import lazyRendererSource from "./LazyConversationMarkdownRenderer.tsx?raw";
import syncShimSource from "./LazyConversationMarkdownRenderer.sync.tsx?raw";

vi.mock("./ConversationMarkdownRenderer", () => ({
  ConversationMarkdownRenderer: function BrokenMarkdownRenderer() {
    throw new Error("synthetic markdown render crash");
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("LazyConversationMarkdownRenderer render-error boundary", () => {
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

  it("keeps the raw markdown readable when the renderer crashes", async () => {
    const raw = "# Title\n\n- item one\n- item two";
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<LazyConversationMarkdownRenderer content={raw} />);
    });

    const html = container.innerHTML;
    // The raw markdown text survives (no blank/broken stream).
    expect(container.textContent).toContain("# Title");
    expect(container.textContent).toContain("- item one");
    // One-line readable note in the default (zh) document language.
    expect(container.textContent).toContain("Markdown 渲染出错，已显示原文。");
    // Degraded into the subtle fallback box, not the rich renderer markup.
    expect(html).toContain("data-markdown-error-fallback");
    expect(html).not.toMatch(/<h1\b/i);
  });

  it("wires the boundary on both the lazy wrapper and the sync test shim", () => {
    expect(lazyRendererSource).toContain("ConversationMarkdownErrorBoundary");
    expect(lazyRendererSource).toContain(
      'from "./LazyConversationMarkdownRenderer.errorBoundary"',
    );
    expect(syncShimSource).toContain("ConversationMarkdownErrorBoundary");
    expect(syncShimSource).toContain(
      'from "./LazyConversationMarkdownRenderer.errorBoundary"',
    );
  });
});
