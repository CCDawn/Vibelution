import { existsSync } from "node:fs";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ConversationImagePreviewDialog } from "./ConversationImagePreviewDialog";
import dialogSource from "./ConversationImagePreviewDialog.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import styles from "./ConversationImagePreviewDialog.styles";

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

  it("renders a preview dialog with download and close actions", () => {
    const onClose = vi.fn();
    const html = renderToStaticMarkup(
      <ConversationImagePreviewDialog image={image} lang="zh" onClose={onClose} />,
    );

    expect(html).toContain('class="vui-components-conversationview imagePreviewOverlay');
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-labelledby="conversation-image-preview-title"');
    expect(html).toContain('aria-describedby="conversation-image-preview-description"');
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain('id="conversation-image-preview-title"');
    expect(html).toContain('id="conversation-image-preview-description"');
    expect(html).toContain('aria-describedby="conversation-image-preview-description"');
    expect(html).toContain('href="/api/artifacts/image/download"');
    expect(html).toContain('download="garden.webp"');
    expect(html).toContain('aria-label="下载图片：霓虹花园"');
    expect(html).toContain('title="下载图片：霓虹花园"');
    expect(html).toContain('aria-label="关闭预览"');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain('src="/api/artifacts/image/preview"');
    expect(html).toContain('alt="霓虹花园"');
  });

  it("keeps the dialog and large image bounded to the viewport", () => {
    expect(styles.imagePreviewOverlay).toContain("fixed");
    expect(styles.imagePreviewOverlay).toContain("inset-0");
    expect(styles.imagePreviewOverlay).toContain("z-50");
    expect(styles.imagePreviewDialog).toContain("max-h-[calc(100vh-2rem)]");
    expect(styles.imagePreviewDialog).toContain("w-[min(100vw-2rem,72rem)]");
    expect(styles.imagePreviewLarge).toContain("max-h-[calc(100vh-8rem)]");
    expect(styles.imagePreviewLarge).toContain("object-contain");
    expect(styles.imagePreviewTitle).toContain("truncate");
    expect(styles.imagePreviewCloseButton).toContain("size-[var(--vui-control-height-sm)]");
    expect(styles.imageDownloadButton).toContain("size-[var(--vui-control-height-sm)]");
  });

  it("keeps keyboard dismissal local to the dialog surface", () => {
    expect(dialogSource).toContain('event.key === "Escape"');
    expect(dialogSource).toContain("event.stopPropagation()");
    expect(dialogSource).toContain("onKeyDown={handleOverlayKeyDown}");
    expect(dialogSource).toContain("autoFocus");
  });
});
