import { existsSync } from "node:fs";

import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import {
  addComparableConversationImageUrl,
  comparableConversationImageUrl,
  conversationImageDownloadName,
  conversationImagePreviewUrl,
  isLikelyConversationImageUrl,
} from "./conversationImagePreview";

describe("conversation image preview boundary", () => {
  it("keeps image URL helpers out of the heavy ConversationView module", () => {
    expect(existsSync(new URL("./conversationImagePreview.ts", import.meta.url))).toBe(true);
    expect(conversationViewSource).toContain('from "./conversationImagePreview"');
    expect(conversationViewSource).not.toContain("function addComparableImageUrl");
    expect(conversationViewSource).not.toContain("function comparableImageUrl");
    expect(conversationViewSource).not.toContain("function previewUrlForImage");
    expect(conversationViewSource).not.toContain("function downloadNameFromUrl");
    expect(conversationViewSource).not.toContain("function isLikelyImageUrl");
  });

  it("normalizes preview URLs by removing download-only query flags", () => {
    expect(conversationImagePreviewUrl(" /files/image.png?download=1&token=abc#preview ")).toBe(
      "/files/image.png?token=abc#preview",
    );
    expect(conversationImagePreviewUrl("/files/image.png?download=true")).toBe("/files/image.png");
    expect(conversationImagePreviewUrl("/files/image.png?download=false")).toBe(
      "/files/image.png?download=false",
    );
  });

  it("builds comparable image URLs from preview URLs", () => {
    const seen = new Set<string>();

    addComparableConversationImageUrl(seen, " /files/image.png?download=true ");
    addComparableConversationImageUrl(seen, "");

    expect(comparableConversationImageUrl("/files/image.png?download=1")).toBe("/files/image.png");
    expect([...seen]).toEqual(["/files/image.png"]);
  });

  it("detects image URLs and extracts download names", () => {
    expect(isLikelyConversationImageUrl("/files/image.webp?download=1")).toBe(true);
    expect(isLikelyConversationImageUrl("/api/artifacts/image/123")).toBe(true);
    expect(isLikelyConversationImageUrl("/files/readme.txt")).toBe(false);
    expect(conversationImageDownloadName("/files/nested/image.webp?download=1#preview")).toBe("image.webp");
    expect(conversationImageDownloadName("")).toBe("");
  });
});
