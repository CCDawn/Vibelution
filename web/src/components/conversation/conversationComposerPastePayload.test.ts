import { describe, expect, it } from "vitest";

import {
  COMPOSER_PASTE_TEXT_CHARACTER_LIMIT,
  buildComposerPastedTextAttachment,
  composerPastedTextAttachmentName,
  extractComposerPastedTextOverflow,
} from "./conversationComposerPastePayload";

function pasteData(overrides: {
  files?: File[];
  types?: string[];
  text?: string;
  withoutGetData?: boolean;
}) {
  return {
    files: overrides.files ?? [],
    types: overrides.types ?? (overrides.text !== undefined ? ["text/plain"] : []),
    getData: overrides.withoutGetData ? undefined : (format: string) => (
      format === "text/plain" ? overrides.text ?? "" : ""
    ),
  };
}

function textOfLength(length: number) {
  return "x".repeat(length);
}

describe("composer paste payload model", () => {
  it("names pasted text attachments 粘贴文本-YYYYMMDD-HHmmss.txt with zero padding", () => {
    expect(composerPastedTextAttachmentName(new Date(2026, 8, 28, 7, 5, 3))).toBe(
      "粘贴文本-20260928-070503.txt",
    );
    expect(composerPastedTextAttachmentName(new Date(2026, 11, 9, 23, 59, 59))).toBe(
      "粘贴文本-20261209-235959.txt",
    );
  });

  it("builds a text/plain file that carries the pasted content", () => {
    const file = buildComposerPastedTextAttachment("大段内容", new Date(2026, 8, 28, 12, 0, 0));
    expect(file.name).toBe("粘贴文本-20260928-120000.txt");
    expect(file.type).toBe("text/plain");
    expect(file.size).toBeGreaterThan(0);
  });

  it("keeps plain text at or below the threshold in the composer", () => {
    expect(COMPOSER_PASTE_TEXT_CHARACTER_LIMIT).toBe(15360);
    expect(extractComposerPastedTextOverflow(pasteData({ text: textOfLength(14999) }))).toBeNull();
    expect(extractComposerPastedTextOverflow(pasteData({ text: textOfLength(15360) }))).toBeNull();
  });

  it("converts plain text above the threshold into a txt attachment", () => {
    const file = extractComposerPastedTextOverflow(
      pasteData({ text: textOfLength(15361) }),
      new Date(2026, 8, 28, 9, 30, 15),
    );
    expect(file).toBeInstanceOf(File);
    expect(file?.name).toBe("粘贴文本-20260928-093015.txt");
    expect(file?.type).toBe("text/plain");
  });

  it("never converts when the clipboard carries a file payload such as an image", () => {
    const imageFile = new File(["png"], "shot.png", { type: "image/png" });
    expect(extractComposerPastedTextOverflow(pasteData({
      files: [imageFile],
      types: ["text/plain", "Files"],
      text: textOfLength(20000),
    }))).toBeNull();
  });

  it("ignores clipboard shapes without readable plain text", () => {
    expect(extractComposerPastedTextOverflow(null)).toBeNull();
    expect(extractComposerPastedTextOverflow(pasteData({ text: textOfLength(20000), withoutGetData: true }))).toBeNull();
    expect(extractComposerPastedTextOverflow(pasteData({ text: "" }))).toBeNull();
    expect(extractComposerPastedTextOverflow(pasteData({ types: ["text/html"], text: textOfLength(20000) }))).toBeNull();
  });
});
