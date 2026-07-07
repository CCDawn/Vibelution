import { existsSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { MarkdownBlock } from "./conversationMarkdownBlocks";
import styles from "./ConversationStreamingResponseContent.styles";
import conversationViewSource from "./ConversationView.tsx?raw";

const classNames = {
  markdownBody: "markdown-body",
  streamingResponseText: "streaming-response",
  markdownBodyWithTable: "markdown-table",
};

describe("ConversationStreamingResponseContent", () => {
  it("keeps streaming markdown projection out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationStreamingResponseContent.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationStreamingResponseContent"');
    expect(conversationViewSource).not.toContain("function StreamingResponseContent");
    expect(conversationViewSource).not.toContain("projectStreamingMarkdownBlocks");
  });

  it("renders projected streaming markdown blocks through the caller renderer", async () => {
    const { ConversationStreamingResponseContent } = await import("./ConversationStreamingResponseContent");
    const html = renderToStaticMarkup(
      <ConversationStreamingResponseContent
        content={"# 标题\n\n正文"}
        classNames={classNames}
        renderBlock={(block: MarkdownBlock, index: number) => (
          <span key={index} data-block-type={block.type}>
            {"content" in block ? String(block.content) : block.type}
          </span>
        )}
      />,
    );

    expect(html).toContain('class="markdown-body streaming-response"');
    expect(html).toContain('data-block-type="heading"');
    expect(html).toContain("标题");
    expect(html).toContain('data-block-type="paragraph"');
    expect(html).toContain("正文");
  });

  it("adds the table class only when the projected stream contains a table", async () => {
    const { ConversationStreamingResponseContent } = await import("./ConversationStreamingResponseContent");
    const html = renderToStaticMarkup(
      <ConversationStreamingResponseContent
        content={"| A | B |\n| --- | --- |\n| 1 | 2 |"}
        classNames={classNames}
        renderBlock={(block: MarkdownBlock, index: number) => <span key={index}>{block.type}</span>}
      />,
    );

    expect(html).toContain('class="markdown-body streaming-response markdown-table"');
  });

  it("keeps stable streaming markdown blocks behind a memo boundary", async () => {
    const source = await import("./ConversationStreamingResponseContent.tsx?raw").then((module) => module.default);

    expect(source).toContain('from "./codexStreamController"');
    expect(source).toContain("createCodexStreamController");
    expect(source).toContain("const StableStreamingMarkdownBlocks = React.memo");
    expect(source).toContain("stableText={markdownProjection.stableText}");
    expect(source).toContain("blocks={markdownProjection.stableBlocks}");
    expect(source).toContain("blocks={markdownProjection.liveBlocks}");
    expect(source).not.toContain("const blocks = markdownProjection.blocks");
    expect(source).not.toContain("blocks.map((block, index) => renderBlock(block, index))");
  });

  it("keeps streaming text bounded for long tokens while preserving the table width override", () => {
    expect(styles.markdownBody).toContain("max-w-[min(100%,76ch)]");
    expect(styles.markdownBody).toContain("whitespace-normal");
    expect(styles.markdownBody).toContain("break-words");
    expect(styles.markdownBody).toContain("[overflow-wrap:anywhere]");
    expect(styles.streamingResponseText).toContain("whitespace-normal");
    expect(styles.streamingResponseText).toContain("break-words");
    expect(styles.streamingResponseText).toContain("[overflow-wrap:anywhere]");
    expect(styles.markdownBodyWithTable).toContain("max-w-full");
    expect(styles.markdownBodyWithTable).not.toContain("max-w-[min(100%,76ch)]");
  });
});
