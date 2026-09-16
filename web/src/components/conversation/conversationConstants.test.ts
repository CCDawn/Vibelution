import { describe, expect, it } from "vitest";

import {
  composerAttachmentAcceptAttribute,
  composerFileExtension,
  isComposerAttachableFile,
  isComposerDocumentFile,
} from "./conversationConstants";

function fileWith(name: string, type = "", size = 10): File {
  const file = new File([new Uint8Array(size)], name, { type });
  Object.defineProperty(file, "size", { value: size });
  return file;
}

describe("conversationConstants composer attachment helpers", () => {
  it("detects document files by extension regardless of mime type", () => {
    expect(isComposerDocumentFile(fileWith("run.csv", "text/csv"))).toBe(true);
    expect(isComposerDocumentFile(fileWith("notes.md"))).toBe(true);
    expect(isComposerDocumentFile(fileWith("paper.PDF"))).toBe(true);
    expect(isComposerDocumentFile(fileWith("archive.exe", "application/octet-stream"))).toBe(false);
    expect(isComposerDocumentFile(fileWith("no-extension"))).toBe(false);
  });

  it("accepts images and documents for paste and drop targets", () => {
    expect(isComposerAttachableFile(fileWith("shot.png", "image/png"))).toBe(true);
    expect(isComposerAttachableFile(fileWith("data.tsv", "text/tab-separated-values"))).toBe(true);
    expect(isComposerAttachableFile(fileWith("clip.exe", "application/octet-stream"))).toBe(false);
    expect(isComposerAttachableFile(fileWith("photo.gif", "image/gif"))).toBe(true);
  });

  it("reads lowercase extensions", () => {
    expect(composerFileExtension(fileWith("DATA.JSON"))).toBe("json");
    expect(composerFileExtension(fileWith("readme"))).toBe("");
  });

  it("builds the file input accept attribute from images and document extensions", () => {
    const accept = composerAttachmentAcceptAttribute();
    expect(accept).toContain("image/png");
    expect(accept).toContain(".md");
    expect(accept).toContain(".csv");
    expect(accept).toContain(".pdf");
    expect(accept).not.toContain(".exe");
  });
});
