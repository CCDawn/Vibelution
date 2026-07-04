import { existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import { parseStreamingMarkdownBlocks } from "./streamingMarkdown";

describe("conversation markdown block boundary", () => {
  it("keeps markdown block parsing out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./conversationMarkdownBlocks.ts", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./conversationMarkdownBlocks"');
    expect(conversationViewSource).not.toContain("function parseMarkdownBlocks");
    expect(conversationViewSource).not.toContain("function isMarkdownTableHeader");
    expect(conversationViewSource).not.toContain("function isMarkdownTableRow");
    expect(conversationViewSource).not.toContain("function isMarkdownTableSeparator");
    expect(conversationViewSource).not.toContain("function parseMarkdownTableRow");
  });

  it("uses the shared streaming markdown block parser for completed conversation text", async () => {
    const { parseConversationMarkdownBlocks } = await import("./conversationMarkdownBlocks");
    const content = [
      "## 总结",
      "",
      "> 关键观察",
      "",
      "| 指标 | 结果 |",
      "| --- | --- |",
      "| 缓存 | 命中 |",
      "",
      "```ts",
      "const value = 1;",
      "```",
    ].join("\n");

    expect(parseConversationMarkdownBlocks(content)).toEqual(parseStreamingMarkdownBlocks(content));
  });
});
