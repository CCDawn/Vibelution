import { describe, expect, it } from "vitest";

import {
  clearSessionDraftForSubmittedTurn,
  classifyComposerImageFiles,
  MAX_COMPOSER_IMAGE_BYTES,
  mergeComposerImageAttachments,
  resolveComposerSubmitGuard,
  restoreSubmittedDraftIfComposerStillEmpty,
  sessionReferenceId,
} from "./chatComposerSubmitModel";

describe("chatComposerSubmitModel", () => {
  it("classifies composer image files by type and size", () => {
    const ok = new File([new Uint8Array([1, 2, 3])], "ok.png", { type: "image/png" });
    const badType = new File([new Uint8Array([1])], "bad.gif", { type: "image/gif" });
    const tooBig = new File([new Uint8Array(MAX_COMPOSER_IMAGE_BYTES + 1)], "big.jpg", { type: "image/jpeg" });
    const result = classifyComposerImageFiles([ok, badType, tooBig], {
      createObjectUrl: () => "blob:test",
      nowMs: 1000,
      randomId: () => "abc",
    });
    expect(result.accepted).toHaveLength(1);
    expect(result.accepted[0]?.filename).toBe("ok.png");
    expect(result.accepted[0]?.previewUrl).toBe("blob:test");
    expect(result.rejected).toEqual(["bad.gif", "big.jpg"]);
  });

  it("merges image attachments with a max cap", () => {
    const existing = [
      { id: "1", file: new File([], "a.png"), filename: "a.png", previewUrl: "a", sizeBytes: 1, contentType: "image/png" },
      { id: "2", file: new File([], "b.png"), filename: "b.png", previewUrl: "b", sizeBytes: 1, contentType: "image/png" },
      { id: "3", file: new File([], "c.png"), filename: "c.png", previewUrl: "c", sizeBytes: 1, contentType: "image/png" },
    ];
    const incoming = [
      { id: "4", file: new File([], "d.png"), filename: "d.png", previewUrl: "d", sizeBytes: 1, contentType: "image/png" },
      { id: "5", file: new File([], "e.png"), filename: "e.png", previewUrl: "e", sizeBytes: 1, contentType: "image/png" },
    ];
    expect(mergeComposerImageAttachments(existing, incoming, 4).map((item) => item.id)).toEqual(["1", "2", "3", "4"]);
  });

  it("resolves composer submit guards", () => {
    expect(resolveComposerSubmitGuard({
      composerDisabled: true,
      content: "hi",
      imageAttachmentCount: 0,
      referenceAttachmentCount: 0,
    })).toBe("composer_disabled");
    expect(resolveComposerSubmitGuard({
      composerDisabled: false,
      content: "",
      imageAttachmentCount: 0,
      referenceAttachmentCount: 0,
    })).toBe("empty_content");
    expect(resolveComposerSubmitGuard({
      composerDisabled: false,
      content: "hi",
      imageAttachmentCount: 0,
      referenceAttachmentCount: 0,
    })).toBe("");
    expect(resolveComposerSubmitGuard({
      composerDisabled: false,
      content: "",
      imageAttachmentCount: 1,
      referenceAttachmentCount: 0,
    })).toBe("");
  });

  it("clears drafts on submit and restores only when still empty", () => {
    expect(clearSessionDraftForSubmittedTurn({ s1: "hello" }, "s1")).toEqual({ s1: "" });
    expect(clearSessionDraftForSubmittedTurn({ s1: "" }, "s1")).toEqual({ s1: "" });
    expect(restoreSubmittedDraftIfComposerStillEmpty({ s1: "" }, "s1", "hello")).toEqual({ s1: "hello" });
    expect(restoreSubmittedDraftIfComposerStillEmpty({ s1: "typed" }, "s1", "hello")).toEqual({ s1: "typed" });
  });

  it("resolves session reference ids", () => {
    expect(sessionReferenceId({ referenceId: "session:abc", kind: "session", sessionId: "abc" })).toBe("session:abc");
    expect(sessionReferenceId({ kind: "session", sessionId: "abc" } as never)).toBe("abc");
  });
});
