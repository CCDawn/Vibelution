import { describe, expect, it } from "vitest";

import { attachmentSizeLabel, isImageAttachment, isUserSecretAttachment } from "./attachmentPresentation";

describe("attachmentPresentation", () => {
  it("classifies images by kind, then MIME, then the legacy imageUrl fallback", () => {
    expect(isImageAttachment({ kind: "user_image", contentType: "image/png" })).toBe(true);
    expect(isImageAttachment({ kind: "image" })).toBe(true);
    expect(isImageAttachment({ kind: "user_document", contentType: "application/pdf" })).toBe(false);
    expect(isImageAttachment({ kind: "user_document", imageUrl: "/api/artifacts/doc.md" })).toBe(false);
    expect(isImageAttachment({ contentType: "image/webp" })).toBe(true);
    expect(isImageAttachment({ contentType: "text/markdown" })).toBe(false);
    expect(isImageAttachment({ imageUrl: "/api/artifacts/legacy.png" })).toBe(true);
    expect(isImageAttachment({})).toBe(false);
  });

  it("registers user_secret kinds and never lets them enter the image branch", () => {
    expect(isUserSecretAttachment({ kind: "user_secret" })).toBe(true);
    expect(isUserSecretAttachment({ kind: "secret" })).toBe(true);
    expect(isUserSecretAttachment({ kind: "user_image" })).toBe(false);
    expect(isUserSecretAttachment({})).toBe(false);
    // Even a hostile field combination (image MIME + legacy imageUrl) cannot
    // turn a privacy attachment into a previewable image.
    expect(isImageAttachment({ kind: "user_secret", contentType: "image/png", imageUrl: "data:image/png;base64,QQ==" })).toBe(false);
    expect(isImageAttachment({ kind: "secret", imageUrl: "blob:preview" })).toBe(false);
  });

  it("formats compact size labels and hides unknown sizes", () => {
    expect(attachmentSizeLabel(4096)).toBe("4 KB");
    expect(attachmentSizeLabel(256)).toBe("1 KB");
    expect(attachmentSizeLabel(2.5 * 1024 * 1024)).toBe("2.5 MB");
    expect(attachmentSizeLabel(12 * 1024 * 1024)).toBe("12 MB");
    expect(attachmentSizeLabel(0)).toBe("");
    expect(attachmentSizeLabel(undefined)).toBe("");
  });
});
