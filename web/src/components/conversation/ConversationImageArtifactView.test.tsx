import { existsSync } from "node:fs";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ImageArtifactMessage } from "./conversationMessagePredicates";
import conversationViewSource from "./ConversationView.tsx?raw";
import styles from "./ConversationImageArtifactView.styles";

const artifact: ImageArtifactMessage = {
  imageUrl: "/api/artifacts/image/preview",
  downloadUrl: "/api/artifacts/image/download",
  prompt: "霓虹花园",
  artifactId: "garden.webp",
  size: "1024x1024",
  quality: "high",
  model: "image-2",
};

describe("ConversationImageArtifactView", () => {
  it("keeps image artifact rendering out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./ConversationImageArtifactView.tsx", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./ConversationImageArtifactView"');
    expect(conversationViewSource).not.toContain("function renderImageArtifact");
    expect(conversationViewSource).not.toContain("const metaItems = [artifact.size, artifact.quality, artifact.model]");
  });

  it("renders generated image artifact preview, metadata, and download affordance", async () => {
    const { ConversationImageArtifactView } = await import("./ConversationImageArtifactView");
    const html = renderToStaticMarkup(
      <ConversationImageArtifactView artifact={artifact} lang="zh" onPreviewImage={vi.fn()} />,
    );

    expect(html).toContain('class="vui-components-conversationview imageArtifact');
    expect(html).toContain('aria-label="预览图片"');
    expect(html).toContain('alt=""');
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("霓虹花园");
    expect(html).toContain("1024x1024 · high · image-2");
    expect(html).toContain('href="/api/artifacts/image/download"');
    expect(html).toContain('download="garden.webp"');
    expect(html).toContain('aria-label="下载图片"');
  });

  it("separates the preview frame from icon-only download controls", () => {
    expect(styles.imageArtifact).toContain("grid");
    expect(styles.imageArtifactFooter).toContain("grid-cols-[minmax(0,1fr)_auto]");
    expect(styles.imageArtifactFrame).toContain("aspect-square");
    expect(styles.imageArtifactFrame).toContain("overflow-hidden");
    expect(styles.imagePreview).toContain("size-full");
    expect(styles.imagePreview).toContain("object-cover");
    expect(styles.imagePreviewButton).toContain("p-0");
    expect(styles.imagePreviewButton).not.toContain("imageArtifactFrame");
    expect(styles.imagePreviewButton).not.toContain("bg-[var(--vui-control-muted)]");
    expect(styles.imageDownloadButton).toContain("size-[var(--vui-control-height-sm)]");
  });
});
