import { describe, expect, it } from "vitest";

import {
  buildFileReferencePayload,
  buildKnowledgeBaseReferencePayload,
  buildKnowledgeItemReferencePayload,
  clearSessionDraftForSubmittedTurn,
  classifyComposerFiles,
  classifyComposerImageFiles,
  MAX_COMPOSER_DOCUMENT_BYTES,
  MAX_COMPOSER_IMAGE_BYTES,
  mergeComposerAttachments,
  mergeComposerAttachmentsWithRejections,
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

  it("classifies composer files into image and document attachments", () => {
    const image = new File([new Uint8Array([1])], "shot.png", { type: "image/png" });
    const csv = new File([new Uint8Array([2])], "run.csv", { type: "text/csv" });
    const noType = new File([new Uint8Array([3])], "notes.md");
    const oversize = new File([new Uint8Array(MAX_COMPOSER_DOCUMENT_BYTES + 1)], "big.json", { type: "application/json" });
    const unsupported = new File([new Uint8Array([5])], "binary.exe", { type: "application/octet-stream" });
    const result = classifyComposerFiles([image, csv, noType, oversize, unsupported], {
      createObjectUrl: () => "blob:test",
      nowMs: 2000,
      randomId: () => "id",
    });
    expect(result.accepted.map((item) => [item.filename, item.kind])).toEqual([
      ["shot.png", "image"],
      ["run.csv", "document"],
      ["notes.md", "document"],
    ]);
    expect(result.rejected).toEqual(["big.json", "binary.exe"]);
  });

  it("merges composer attachments with per-kind caps", () => {
    const make = (id: string, kind: "image" | "document") => ({
      id,
      file: new File([], id),
      filename: id,
      previewUrl: id,
      sizeBytes: 1,
      contentType: kind === "image" ? "image/png" : "text/plain",
      kind,
    });
    const existing = [make("img-1", "image"), make("doc-1", "document")];
    const incoming = [make("img-2", "image"), make("doc-2", "document"), make("img-3", "image")];
    const merged = mergeComposerAttachments(existing, incoming, { maxTotal: 8, maxImages: 4, maxDocuments: 4 });
    expect(merged.map((item) => item.id)).toEqual(["img-1", "doc-1", "img-2", "doc-2", "img-3"]);
    const overImages = mergeComposerAttachments(
      [make("i1", "image"), make("i2", "image"), make("i3", "image"), make("i4", "image")],
      [make("i5", "image"), make("d9", "document")],
      { maxTotal: 8, maxImages: 4, maxDocuments: 4 },
    );
    // the newest image that breaks the per-image cap is dropped; docs always stay
    expect(overImages.map((item) => item.id)).toEqual(["i1", "i2", "i3", "i4", "d9"]);
  });

  it("enforces the document cap and reports rejected attachments in order", () => {
    const make = (id: string, kind: "image" | "document") => ({
      id,
      file: new File([], id),
      filename: id,
      previewUrl: id,
      sizeBytes: 1,
      contentType: kind === "image" ? "image/png" : "text/plain",
      kind,
    });
    const result = mergeComposerAttachmentsWithRejections(
      [make("doc-1", "document"), make("img-1", "image")],
      [make("doc-2", "document"), make("doc-3", "document"), make("img-2", "image")],
      { maxTotal: 8, maxImages: 4, maxDocuments: 2 },
    );
    expect(result.attachments.map((item) => item.id)).toEqual(["doc-1", "img-1", "doc-2", "img-2"]);
    expect(result.rejected.map((item) => item.filename)).toEqual(["doc-3"]);
    const overExisting = mergeComposerAttachmentsWithRejections(
      [make("old-1", "document"), make("old-2", "document"), make("old-3", "document")],
      [make("new-image", "image")],
      { maxDocuments: 2 },
    );
    expect(overExisting.attachments.map((item) => item.id)).toEqual(["old-1", "old-2", "new-image"]);
    expect(overExisting.rejected.map((item) => item.id)).toEqual(["old-3"]);
  });

  it("builds knowledge and file reference payloads", () => {
    expect(buildKnowledgeBaseReferencePayload(" kb1 ", "Lab KB")).toEqual({
      referenceId: "knowledge-base:kb1",
      kind: "knowledge_base",
      knowledgeBaseId: "kb1",
      title: "Lab KB",
      createdAt: expect.any(String),
    });
    expect(buildKnowledgeItemReferencePayload("kb1", " item9 ", "Protocol").referenceId).toBe("knowledge-item:item9");
    expect(buildFileReferencePayload("user-doc-1.csv", "run.csv")).toEqual({
      referenceId: "file:user-doc-1.csv",
      kind: "file",
      artifactId: "user-doc-1.csv",
      title: "run.csv",
      createdAt: expect.any(String),
    });
  });

  it("resolves session reference ids", () => {
    expect(sessionReferenceId({ referenceId: "session:abc", kind: "session", sessionId: "abc" })).toBe("session:abc");
    expect(sessionReferenceId({ kind: "session", sessionId: "abc" } as never)).toBe("abc");
  });
});
