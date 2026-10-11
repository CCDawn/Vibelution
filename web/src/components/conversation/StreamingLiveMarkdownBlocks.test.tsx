// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { VuiProvider } from "../vui";
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

  it("renders a live workspace file link with the side-column menu target", () => {
    const html = renderToStaticMarkup(
      <StreamingLiveMarkdownBlocks
        blocks={parseStreamingMarkdownBlocks("看 [说明](notes/a.md)\n\n- [清单](docs/b.md)")}
        classNames={classNames}
        workspaceRoot="C:/repo"
        language="zh"
        onOpenRailFile={() => undefined}
      />,
    );

    expect(html).toContain('data-markdown-workspace-file-link="true"');
    expect(html).toContain('title="C:\\repo\\notes\\a.md"');
    expect(html).toContain('title="C:\\repo\\docs\\b.md"');
    expect(html).not.toContain('href="notes/a.md"');
  });

  it("keeps an ordinary web link as an anchor while the file menu is available", () => {
    const html = renderToStaticMarkup(
      <StreamingLiveMarkdownBlocks
        blocks={parseStreamingMarkdownBlocks("看 [文档](https://example.com)")}
        classNames={classNames}
        workspaceRoot="C:/repo"
        language="zh"
        onOpenRailFile={() => undefined}
      />,
    );

    expect(html).toContain('<a class="test-inline-link" href="https://example.com">文档</a>');
    expect(html).not.toContain("data-markdown-workspace-file-link");
  });

  it("opens the live file link in the side column from the menu", async () => {
    const onOpenRailFile = vi.fn();
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <VuiProvider>
          <StreamingLiveMarkdownBlocks
            blocks={parseStreamingMarkdownBlocks("看 [说明](notes/a.md)")}
            classNames={classNames}
            workspaceRoot="C:/repo"
            language="zh"
            onOpenRailFile={onOpenRailFile}
          />
        </VuiProvider>,
      );
    });
    try {
      const anchor = host.querySelector("a");
      await act(async () => {
        anchor?.dispatchEvent(new MouseEvent("contextmenu", {
          bubbles: true,
          cancelable: true,
          clientX: 8,
          clientY: 10,
        }));
      });
      const item = Array.from(document.querySelectorAll('[role="menuitem"]')).find((node) => (
        node.textContent === "在右栏查看"
      ));
      expect(item).toBeTruthy();
      await act(async () => {
        item?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      });
      expect(onOpenRailFile).toHaveBeenCalledWith("C:\\repo\\notes\\a.md");
    } finally {
      act(() => root.unmount());
      host.remove();
    }
  });
});
