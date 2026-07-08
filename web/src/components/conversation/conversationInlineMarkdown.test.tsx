import { existsSync } from "node:fs";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";

const classNames = {
  inlineCode: "inline-code-class",
  inlineLink: "inline-link-class",
  inlineStrong: "inline-strong-class",
};

describe("conversation inline markdown boundary", () => {
  it("keeps inline markdown rendering out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./conversationInlineMarkdown.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).not.toContain('from "./conversationInlineMarkdown"');
    expect(conversationViewSource).not.toContain("function renderInlineMarkdown");
    expect(conversationViewSource).not.toContain("const inlinePattern =");
  });

  it("renders strong, code, safe links, image downloads, and unsafe link text", async () => {
    const { renderConversationInlineMarkdown } = await import("./conversationInlineMarkdown");
    const html = renderToStaticMarkup(
      <>
        {renderConversationInlineMarkdown(
          [
            "Start **bold `code`**",
            "[image](/files/pic.webp?download=1)",
            "[bad](javascript:alert(1))",
          ].join(" "),
          classNames,
        )}
      </>,
    );

    expect(html).toContain("inline-strong-class");
    expect(html).toContain("inline-code-class");
    expect(html).toContain("inline-link-class");
    expect(html).toContain('href="/files/pic.webp?download=1"');
    expect(html).toContain('download="pic.webp"');
    expect(html).toContain("bad");
    expect(html).not.toContain("javascript:");
  });
});
