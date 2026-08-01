import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import styles from "./ConversationView.styles";
import rendererSource from "./LazyConversationMarkdownRenderer.tsx?raw";

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
