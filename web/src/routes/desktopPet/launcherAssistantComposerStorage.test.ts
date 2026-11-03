import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLauncherComposer, restoreLauncherComposerAttachments, saveLauncherComposer,
  type PersistedLauncherComposer } from "./launcherAssistantComposerStorage";
import type { ComposerImageAttachment } from "../chat/chatComposerSubmitModel";

function memoryStorage() {
  const entries = new Map<string, string>();
  return {
    entries,
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => { entries.set(key, value); },
  };
}

function empty(): PersistedLauncherComposer {
  return { draft: "", outstanding: null, acceptedTurnId: "", queuedAcceptance: null, attachments: [] };
}

function pending(): PersistedLauncherComposer {
  return { ...empty(), draft: "  下一条草稿  ", outstanding: {
    message: "原消息", requestId: "original.request:1-2_3", draftSnapshot: "  原消息  ",
    attachmentIds: ["artifact-1"], attachmentSnapshotIds: ["composer-image-1"], preserveDraft: true,
  } };
}

function chip(overrides: Partial<ComposerImageAttachment> = {}): ComposerImageAttachment {
  return {
    id: "composer-image-1", file: new File([new Uint8Array([1])], "shot.png", { type: "image/png" }),
    filename: "shot.png", previewUrl: "blob:preview", sizeBytes: 1, contentType: "image/png", kind: "image",
    ...overrides,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("launcher assistant composer recovery storage", () => {
  it("round-trips the exact outstanding request and unsent text without sending or replacing IDs", () => {
    const storage = memoryStorage();
    const value = pending();
    expect(saveLauncherComposer("session-1", "floating", value, storage)).toBe(true);
    expect(loadLauncherComposer("session-1", "floating", storage)).toEqual(value);
  });

  it("keeps session and surface states independent", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session-1", "floating", pending(), storage);
    saveLauncherComposer("session-1", "embedded", { ...empty(), draft: "embedded draft" }, storage);
    saveLauncherComposer("session-2", "floating", { ...empty(), draft: "other session" }, storage);
    expect(storage.entries.size).toBe(3);
    expect(loadLauncherComposer("session-1", "floating", storage)).toEqual(pending());
    expect(loadLauncherComposer("session-1", "embedded", storage)?.draft).toBe("embedded draft");
    expect(loadLauncherComposer("session-2", "floating", storage)).toEqual({ ...empty(), draft: "other session" });
  });

  it("overwrites an old outstanding request with native acceptance and then an empty snapshot", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    const accepted = { ...empty(), acceptedTurnId: "turn:1" };
    expect(saveLauncherComposer("session", "floating", accepted, storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(accepted);
    expect(saveLauncherComposer("session", "floating", empty(), storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(empty());
    expect(storage.entries.size).toBe(1);
  });

  it.each([false, true])("preserves queued acceptance observed=%s", observed => {
    const storage = memoryStorage();
    const value = { ...empty(), queuedAcceptance: { id: "queue:1", clientSubmissionId: "request:1", observed } };
    saveLauncherComposer("session", "floating", value, storage);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(value);
  });

  it("persists only uploaded attachment metadata and never a File body, preview or extra Route state", () => {
    const storage = memoryStorage();
    const forbidden = { toJSON: () => { throw new Error("must never serialize extra state"); } };
    const attachments = [
      chip({ id: "chip-uploaded", uploadStatus: "uploaded", artifactId: "user-image-1.png" }),
      chip({ id: "chip-pending", uploadStatus: "pending" }),
      chip({ id: "chip-failed", uploadStatus: "failed" }),
      chip({ id: "chip-uploading", uploadStatus: "uploading", artifactId: undefined }),
    ];
    const value = { ...pending(), attachments, continuation: forbidden, token: forbidden };
    expect(saveLauncherComposer("session", "floating", value, storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual({ ...pending(),
      attachments: [{ id: "chip-uploaded", artifactId: "user-image-1.png", filename: "shot.png",
        contentType: "image/png", sizeBytes: 1, kind: "image" }] });
    const savedSnapshot = JSON.parse([...storage.entries.values()][0]).snapshot;
    expect(Object.keys(savedSnapshot)).toEqual(["draft", "outstanding", "acceptedTurnId", "queuedAcceptance", "attachments"]);
    expect(JSON.stringify(savedSnapshot.attachments)).not.toContain("blob:");
    expect(JSON.stringify(savedSnapshot)).not.toContain("continuation");
  });

  it("loads envelopes written before attachment persistence with an empty tray", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    const [key, raw] = [...storage.entries][0];
    const legacy = JSON.parse(raw);
    delete legacy.snapshot.attachments;
    storage.setItem(key, JSON.stringify(legacy));
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(pending());
  });

  it.each([
    ["non-object attachment row", (row: any) => { row.snapshot.attachments = ["chip"]; }],
    ["unknown attachment field", (row: any) => { row.snapshot.attachments[0].previewUrl = "blob:x"; }],
    ["missing attachment field", (row: any) => { delete row.snapshot.attachments[0].artifactId; }],
    ["bad attachment artifact", (row: any) => { row.snapshot.attachments[0].artifactId = "../escape"; }],
    ["bad attachment size", (row: any) => { row.snapshot.attachments[0].sizeBytes = -1; }],
    ["bad attachment kind", (row: any) => { row.snapshot.attachments[0].kind = "video"; }],
    ["too many attachment rows", (row: any) => {
      row.snapshot.attachments = Array.from({ length: 33 }, (_, index) =>
        ({ id: `chip-${index}`, artifactId: `artifact-${index}`, filename: "f.png", contentType: "image/png", sizeBytes: 1, kind: "image" }));
    }],
  ])("rejects %s without deleting the stored input", (_label, mutate) => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", { ...empty(), attachments: [chip({ uploadStatus: "uploaded", artifactId: "a.png" })] }, storage);
    const [key, raw] = [...storage.entries][0];
    const row = JSON.parse(raw);
    mutate(row);
    const invalid = JSON.stringify(row);
    storage.setItem(key, invalid);
    expect(loadLauncherComposer("session", "floating", storage)).toBeNull();
    expect(storage.getItem(key)).toBe(invalid);
  });

  it("rebuilds tray chips from persisted rows with a placeholder body and no preview", () => {
    const restored = restoreLauncherComposerAttachments([{ id: "chip-1", artifactId: "user-image-1.png",
      filename: "shot.png", contentType: "image/png", sizeBytes: 7, kind: "image" }]);
    expect(restored).toHaveLength(1);
    expect(restored[0]).toMatchObject({ id: "chip-1", artifactId: "user-image-1.png", filename: "shot.png",
      contentType: "image/png", sizeBytes: 7, kind: "image", uploadStatus: "uploaded", previewUrl: "" });
    expect(restored[0].file.name).toBe("shot.png");
    expect(restored[0].file.size).toBe(0);
  });

  it("retains drafts across time without an arbitrary expiration", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    const now = vi.spyOn(Date, "now").mockReturnValue(Number.MAX_SAFE_INTEGER);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(pending());
    now.mockRestore();
  });

  it.each([
    ["old version", (row: any) => { row.version = 0; }],
    ["foreign session", (row: any) => { row.sessionId = "foreign"; }],
    ["foreign surface", (row: any) => { row.surface = "embedded"; }],
    ["extra envelope field", (row: any) => { row.token = "secret"; }],
    ["extra snapshot field", (row: any) => { row.snapshot.continuation = {}; }],
    ["missing snapshot field", (row: any) => { delete row.snapshot.draft; }],
    ["wrong draft type", (row: any) => { row.snapshot.draft = 1; }],
    ["oversized draft", (row: any) => { row.snapshot.draft = "x".repeat(64_001); }],
    ["oversized message", (row: any) => { row.snapshot.outstanding.message = "x".repeat(64_001); }],
    ["oversized draft snapshot", (row: any) => { row.snapshot.outstanding.draftSnapshot = "x".repeat(64_001); }],
    ["invalid request ID", (row: any) => { row.snapshot.outstanding.requestId = "new request"; }],
    ["oversized request ID", (row: any) => { row.snapshot.outstanding.requestId = "x".repeat(129); }],
    ["attachment body", (row: any) => { row.snapshot.outstanding.attachments = [{ dataBase64: "body" }]; }],
    ["artifact path", (row: any) => { row.snapshot.outstanding.attachmentIds = ["../artifact"]; }],
    ["invalid attachment snapshot ID", (row: any) => { row.snapshot.outstanding.attachmentSnapshotIds = [1]; }],
    ["too many attachments", (row: any) => { row.snapshot.outstanding.attachmentIds = Array(33).fill("artifact"); }],
    ["wrong preserveDraft type", (row: any) => { row.snapshot.outstanding.preserveDraft = false; }],
    ["invalid accepted turn", (row: any) => { row.snapshot.acceptedTurnId = {}; }],
    ["wrong receipt observed type", (row: any) => { row.snapshot.queuedAcceptance = { id: "queue", clientSubmissionId: "request", observed: "true" }; }],
    ["extra receipt field", (row: any) => { row.snapshot.queuedAcceptance = { id: "queue", clientSubmissionId: "request", observed: false, turnId: "turn" }; }],
  ])("rejects %s without deleting the stored input", (_label, mutate) => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    const [key, raw] = [...storage.entries][0];
    const row = JSON.parse(raw);
    mutate(row);
    const invalid = JSON.stringify(row);
    storage.setItem(key, invalid);
    expect(loadLauncherComposer("session", "floating", storage)).toBeNull();
    expect(storage.getItem(key)).toBe(invalid);
  });

  it.each(["{", "null", "[]", "x".repeat(1_200_001)])("returns null for corrupt or oversized JSON", raw => {
    expect(loadLauncherComposer("session", "floating", { getItem: () => raw })).toBeNull();
  });

  it("rejects invalid writes instead of truncating or replacing the existing request", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    expect(saveLauncherComposer("session", "floating", { ...empty(), draft: "x".repeat(64_001) }, storage)).toBe(false);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(pending());
    expect(saveLauncherComposer("", "floating", empty(), storage)).toBe(false);
    expect(loadLauncherComposer("", "floating", storage)).toBeNull();
    const sparse = pending();
    sparse.outstanding!.attachmentIds = Array(1);
    expect(saveLauncherComposer("session", "floating", sparse, storage)).toBe(false);
  });

  it("accepts the maximum text size and attachment-only submissions without changing the payload", () => {
    const storage = memoryStorage();
    const value = { ...empty(), draft: "\u0000".repeat(64_000), outstanding: {
      message: "", requestId: "request", draftSnapshot: " ".repeat(64_000), attachmentIds: ["artifact"],
    } };
    expect(saveLauncherComposer("session", "embedded", value, storage)).toBe(true);
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(value);
    expect(saveLauncherComposer("session", "floating", { ...empty(), outstanding: { message: " ", requestId: "request" } }, storage)).toBe(false);
  });

  it("degrades safely when storage is absent, access is blocked or writes exceed quota", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(loadLauncherComposer("session", "floating")).toBeNull();
    expect(saveLauncherComposer("session", "floating", empty())).toBe(false);
    const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("quota"); } };
    expect(loadLauncherComposer("session", "floating", blocked)).toBeNull();
    expect(saveLauncherComposer("session", "floating", empty(), blocked)).toBe(false);
  });
});
