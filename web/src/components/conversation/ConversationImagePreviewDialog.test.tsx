import { existsSync } from "node:fs";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";

const image = {
  src: "/api/artifacts/image/preview",
  alt: "霓虹花园",
  downloadUrl: "/api/artifacts/image/download",
  downloadName: "garden.webp" as const,
};

describe("ConversationImagePreviewDialog", () => {
  it("keeps the image preview dialog out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationImagePreviewDialog.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationImagePreviewDialog"');
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewOverlay}");
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewDialog}");
    expect(conversationViewSource).not.toContain("className={styles.imagePreviewToolbar}");
  });

  it("renders a preview dialog with download and close actions", async () => {
    const { ConversationImagePreviewDialog } = await import("./ConversationImagePreviewDialog");
    const onClose = vi.fn();
    const html = renderToStaticMarkup(
      <ConversationImagePreviewDialog image={image} lang="zh" onClose={onClose} />,
    );

    expect(html).toContain('class="vui-components-conversationview imagePreviewOverlay');
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-label="霓虹花园"');
    expect(html).toContain('href="/api/artifacts/image/download"');
    expect(html).toContain('download="garden.webp"');
    expect(html).toContain('aria-label="下载图片"');
    expect(html).toContain('aria-label="关闭预览"');
    expect(html).toContain('src="/api/artifacts/image/preview"');
    expect(html).toContain('alt="霓虹花园"');
  });
});
