import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { LazyConversationMarkdownRenderer } from "./LazyConversationMarkdownRenderer";
import styles from "./ConversationView.styles";

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
