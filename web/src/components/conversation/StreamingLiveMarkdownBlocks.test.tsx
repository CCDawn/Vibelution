import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMarkdownClassNames } from "./conversationMarkdownTypes";
import { StreamingLiveMarkdownBlocks } from "./StreamingLiveMarkdownBlocks";
import { parseStreamingMarkdownBlocks } from "./streamingMarkdown";

const classNames: ConversationMarkdownClassNames = {
  inlineCode: "test-inline-code",
  inlineLink: "test-inline-link",
  inlineStrong: "test-inline-strong",
  markdownBlockquote: "test-blockquote",
  markdownBody: "test-body",
  markdownBodyWithTable: "test-body-table",
  markdownDivider: "test-divider",
  markdownHeading: "test-heading",
  markdownHeading1: "test-h1",
  markdownHeading2: "test-h2",
  markdownHeading3: "test-h3",
  markdownHeading4: "test-h4",
  markdownTable: "test-table",
  markdownTableWrap: "test-table-wrap",
  messageBody: "test-message-body",
  responseSegmentList: "test-list",
  responseSegmentPre: "test-pre",
};

function renderLive(content: string) {
  return renderToStaticMarkup(
    <StreamingLiveMarkdownBlocks blocks={parseStreamingMarkdownBlocks(content)} classNames={classNames} />,
  );
}

describe("StreamingLiveMarkdownBlocks", () => {
  it("renders live paragraph inline code as a settled-style pill, not bare backticks", () => {
    const html = renderLive("运行 `npm test` 验证");

    expect(html).toContain('<p class="test-message-body">');
    expect(html).toContain('<code class="test-inline-code">npm test</code>');
    // The live tail must never paint the raw delimiters that the settled
    // renderer turns into pills (no streaming-to-settled skin flip).
    expect(html).not.toContain("`");
  });

  it("renders live paragraph links and strong with the settled inline tokens", () => {
    const html = renderLive("看 [文档](https://example.com) 与 **重要** 部分");

    expect(html).toContain('<a class="test-inline-link" href="https://example.com">文档</a>');
    expect(html).toContain('<strong class="test-inline-strong">重要</strong>');
    expect(html).not.toContain("**");
    expect(html).not.toContain("](");
  });

  it("keeps plain live paragraph text free of inline wrappers", () => {
    const html = renderLive("普通流式段落");

    expect(html).toContain('<p class="test-message-body">普通流式段落</p>');
    expect(html).not.toContain("<code");
    expect(html).not.toContain("<strong");
  });
});
