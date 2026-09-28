// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import styles from "./ConversationStreamingResponseContent.styles";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// Mount counter for the shared lazy stable renderer: the streaming→settled
// flip must keep the same renderer instance mounted (no subtree remount).
const lazyRendererMountCount = vi.hoisted(() => ({ value: 0 }));

// Transparent pass-through wrapper (same props) that counts mounts of the
// lazy stable renderer without changing rendered output.
vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  const CountingLazyRenderer = (props: React.ComponentProps<typeof ConversationMarkdownRenderer>) => {
    React.useEffect(() => {
      lazyRendererMountCount.value += 1;
    }, []);
    return <ConversationMarkdownRenderer {...props} />;
  };
  return { LazyConversationMarkdownRenderer: CountingLazyRenderer };
});

const classNames = {
  ...styles,
  markdownBody: "markdown-body",
  streamingResponseText: "streaming-response",
  markdownBodyWithTable: "markdown-table",
};

describe("ConversationStreamingResponseContent settle flip", () => {
  it("keeps the shared stable renderer mounted when the same message settles (no remount on the flip)", async () => {
    const { ConversationStreamingResponseContent } = await import("./ConversationStreamingResponseContent");
    lazyRendererMountCount.value = 0;
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const renderWith = (isStreaming: boolean) => {
      act(() => {
        root.render(
          <ConversationStreamingResponseContent
            content={"完成的段落。\n\n未完成的尾"}
            isStreaming={isStreaming}
            classNames={classNames}
          />,
        );
      });
    };
    try {
      renderWith(true);
      expect(document.querySelector("[data-streaming-live-tail]")).not.toBeNull();

      renderWith(false);
      // Settled: live tail is gone and the full text lives in the shared
      // stable zone through the same component instance.
      expect(document.querySelector("[data-streaming-live-tail]")).toBeNull();
      expect(container.textContent).toContain("完成的段落");
      expect(container.textContent).toContain("未完成的尾");
      // Exactly one mount across the flip proves the markdown subtree was
      // never unmounted/remounted when streaming settled.
      expect(lazyRendererMountCount.value).toBe(1);
    } finally {
      act(() => {
        root.unmount();
      });
      container.remove();
    }
  });

  it("renders settled text without the live-tail pipeline when isStreaming is false", async () => {
    const { ConversationStreamingResponseContent } = await import("./ConversationStreamingResponseContent");
    const html = renderToStaticMarkup(
      <ConversationStreamingResponseContent
        content={"完成的段落。\n\n未完成的尾"}
        isStreaming={false}
        classNames={classNames}
      />,
    );

    expect(html).not.toContain("data-streaming-live-tail");
    expect(html).toContain("完成的段落");
    expect(html).toContain("未完成的尾");
  });
});
