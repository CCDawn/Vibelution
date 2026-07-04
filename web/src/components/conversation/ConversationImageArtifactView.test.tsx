import { existsSync } from "node:fs";

import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ImageArtifactMessage } from "./conversationMessagePredicates";
import conversationViewSource from "./ConversationView.tsx?raw";

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
    expect(html).toContain('alt="霓虹花园"');
    expect(html).toContain("霓虹花园");
    expect(html).toContain("1024x1024 · high · image-2");
    expect(html).toContain('href="/api/artifacts/image/download"');
    expect(html).toContain('download="garden.webp"');
    expect(html).toContain('aria-label="下载图片"');
  });
});
