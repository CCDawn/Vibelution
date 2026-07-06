import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import styles from "./ChatFileWorkspaceTabs.styles";
import source from "./ChatFileWorkspaceTabs.tsx?raw";
import { ChatFileWorkspaceTabs } from "./ChatFileWorkspaceTabs";

describe("ChatFileWorkspaceTabs layout contract", () => {
  it("renders file tabs with current-tab semantics and hidden close icons", () => {
    const markup = renderToStaticMarkup(
      <ChatFileWorkspaceTabs
        activeTab="src/routes/chat/very-long-active-file-name-with-many-segments.tsx"
        closePreviewTabLabel="关闭预览"
        hidden={false}
        openTabs={[
          "src/routes/chat/very-long-active-file-name-with-many-segments.tsx",
          "docs/release-notes.md",
        ]}
        onCloseTab={() => undefined}
        onOpenTab={() => undefined}
      />,
    );

    expect(markup.match(/role="tab"/g)?.length).toBe(2);
    expect(markup).toContain('aria-selected="true"');
    expect(markup).toContain('aria-selected="false"');
    expect(markup).toContain('aria-current="page"');
    expect(markup).toContain('title="src/routes/chat/very-long-active-file-name-with-many-segments.tsx"');
    expect(markup).toContain('aria-label="关闭预览 very-long-active-file-name-with-many-segments.tsx"');
    expect(markup).toContain('aria-hidden="true"');
  });

  it("keeps long file names from widening the tab strip", () => {
    expect(styles.fileTab).toContain("overflow-hidden");
    expect(styles.fileTab).toContain("max-w-[min(100%,18rem)]");
    expect(styles.fileTabButton).toContain("truncate");
    expect(styles.fileTabButton).toContain("overflow-hidden");
    expect(styles.fileTabButton).toContain("[&_[data-slot=vui-button-content]]:contents");
    expect(styles.fileTabButton).toContain("[&_[data-slot=vui-button-label]]:truncate");
    expect(styles.fileTabClose).toContain("size-[var(--vui-control-height-xs)]");
    expect(source).toContain("<X size={14} aria-hidden=\"true\" />");
  });
});
