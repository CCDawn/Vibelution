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

function question() {
  return { id: "question:1", questionText: "先处理哪一项？", askedAt: "2026-11-05T01:00:00Z", turnId: "turn:1" };
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
  it("round-trips reference-only original requests and a continuation snapshot without replacing their IDs", () => {
    const storage = memoryStorage();
    const references = [{ kind: "message", referenceId: "message:m1", sourceSessionId: "source-session", sourceMessageId: "m1", quote: "原引用" }];
    const continuation = { requestId: "continue-original", expected: { turnId: "t1", headId: "h1", ledgerSeq: 4, agentId: "a1" }, accepted: false };
    const value = { ...empty(), references, outstanding: { message: "", requestId: "reference-original", references }, continuation };
    expect(saveLauncherComposer("session", "embedded", value, storage)).toBe(true);
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(value);
  });

  it.each([
    { kind: "message", sourceMessageId: "m1", path: "C:/private" },
    { kind: "message", sourceMessageId: "m1", token: "private" },
    { kind: "message", sourceMessageId: "../m1" },
    { kind: "message", sourceMessageId: "m1", quote: "x".repeat(64_001) },
  ])("rejects unsafe recovery references without overwriting the last snapshot", reference => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "embedded", empty(), storage);
    expect(saveLauncherComposer("session", "embedded", { ...empty(), outstanding: {
      message: "request", requestId: "original", references: [reference],
    } }, storage)).toBe(false);
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(empty());
  });

  it.each([
    { requestId: "invalid request" }, { accepted: "yes" }, { token: "secret" },
    { expected: { turnId: "t", headId: "h", agentId: "../agent", ledgerSeq: 1 } },
    { expected: { turnId: "t", headId: "h", agentId: "a", ledgerSeq: 0 } },
    { expected: { turnId: "t", headId: "h", agentId: "a", ledgerSeq: 1, path: "C:/private" } },
  ])("rejects an invalid continuation without replacing the previous recovery envelope", patch => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "embedded", empty(), storage);
    const continuation = { requestId: "original", expected: { turnId: "t", headId: "h", agentId: "a", ledgerSeq: 1 }, accepted: false, ...patch };
    // Exercise the runtime boundary with data that did not pass TypeScript.
    expect(saveLauncherComposer("session", "embedded", { ...empty(), continuation } as Parameters<typeof saveLauncherComposer>[2], storage)).toBe(false);
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(empty());
  });

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

  it("round-trips question drafts independently across both surfaces and sessions", () => {
    const storage = memoryStorage();
    for (const session of ["session-1", "session-2"]) {
      for (const surface of ["floating", "embedded"] as const) {
        const value = { ...empty(), draft: `ordinary ${session} ${surface}`,
          questionDraft: { question: question(), value: `  answer ${session} ${surface}\n  ` } };
        expect(saveLauncherComposer(session, surface, value, storage)).toBe(true);
      }
    }
    expect(storage.entries.size).toBe(4);
    for (const session of ["session-1", "session-2"]) {
      for (const surface of ["floating", "embedded"] as const) {
        expect(loadLauncherComposer(session, surface, storage)).toEqual({ ...empty(),
          draft: `ordinary ${session} ${surface}`,
          questionDraft: { question: question(), value: `  answer ${session} ${surface}\n  ` } });
      }
    }
  });

  it("restores an unconfirmed answer's original request and question while retaining the ordinary draft and tray", () => {
    const storage = memoryStorage();
    const value: PersistedLauncherComposer = { ...pending(),
      questionDraft: { question: question(), value: "  先修复显示\n保留回答  " },
      outstanding: { message: "先修复显示\n保留回答", requestId: "original.answer:1",
        draftSnapshot: "  先修复显示\n保留回答  ", preserveDraft: true, answerQuestion: question() },
      attachments: [{ id: "ordinary-chip", artifactId: "ordinary-artifact.png", filename: "shot.png",
        contentType: "image/png", sizeBytes: 1, kind: "image" }],
    };
    expect(saveLauncherComposer("session", "embedded", value, storage)).toBe(true);
    const restored = loadLauncherComposer("session", "embedded", storage)!;
    expect(restored).toEqual(value);
    expect(restored.questionDraft).not.toBe(value.questionDraft);
    expect(restored.questionDraft!.question).not.toBe(value.questionDraft!.question);
    expect(restored.outstanding!.answerQuestion).not.toBe(value.outstanding!.answerQuestion);
    expect(restored.outstanding!.answerQuestion).not.toBe(restored.questionDraft!.question);
    restored.questionDraft!.question.id = "changed";
    restored.outstanding!.answerQuestion!.questionText = "changed";
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(value);
  });

  it("preserves explicit null clearing and accepts legacy questions with empty time and turn IDs", () => {
    const storage = memoryStorage();
    const legacyQuestion = { ...question(), askedAt: "", turnId: "" };
    const value = { ...pending(), questionDraft: { question: legacyQuestion, value: "" },
      outstanding: { message: "回答", requestId: "request:1", preserveDraft: true as const, answerQuestion: legacyQuestion } };
    expect(saveLauncherComposer("session", "floating", value, storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(value);
    const cleared = { ...empty(), questionDraft: null };
    expect(saveLauncherComposer("session", "floating", cleared, storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(cleared);
    expect(JSON.parse([...storage.entries.values()][0]).snapshot.questionDraft).toBeNull();
  });

  it.each([
    ["unknown field", (row: any) => { row.extra = "untrusted"; }],
    ["missing id", (row: any) => { delete row.id; }],
    ["missing question text", (row: any) => { delete row.questionText; }],
    ["missing askedAt", (row: any) => { delete row.askedAt; }],
    ["missing turnId", (row: any) => { delete row.turnId; }],
    ["invalid id", (row: any) => { row.id = "question id"; }],
    ["empty id", (row: any) => { row.id = ""; }],
    ["non-string id", (row: any) => { row.id = 1; }],
    ["oversized id", (row: any) => { row.id = "x".repeat(256); }],
    ["non-string text", (row: any) => { row.questionText = 1; }],
    ["oversized text", (row: any) => { row.questionText = "x".repeat(4_001); }],
    ["non-string askedAt", (row: any) => { row.askedAt = 1; }],
    ["oversized askedAt", (row: any) => { row.askedAt = "x".repeat(65); }],
    ["non-string turnId", (row: any) => { row.turnId = 1; }],
    ["invalid turnId", (row: any) => { row.turnId = "turn id"; }],
    ["oversized turnId", (row: any) => { row.turnId = "x".repeat(256); }],
  ])("rejects question metadata with %s in both recovery fields", (_label, mutate) => {
    for (const source of ["draft", "submission"]) {
      const storage = memoryStorage();
      const value = { ...pending(), questionDraft: { question: question(), value: "回答" },
        outstanding: { ...pending().outstanding!, answerQuestion: question() } };
      saveLauncherComposer("session", "floating", value, storage);
      const [key, raw] = [...storage.entries][0];
      const row = JSON.parse(raw);
      mutate(source === "draft" ? row.snapshot.questionDraft.question : row.snapshot.outstanding.answerQuestion);
      expect(saveLauncherComposer("session", "floating", row.snapshot, storage)).toBe(false);
      expect(loadLauncherComposer("session", "floating", storage)).toEqual(value);
      const invalid = JSON.stringify(row);
      storage.setItem(key, invalid);
      expect(loadLauncherComposer("session", "floating", storage)).toBeNull();
      expect(storage.getItem(key)).toBe(invalid);
    }
  });

  it.each([
    ["non-object question draft", (row: any) => { row.questionDraft = "answer"; }],
    ["unknown question draft field", (row: any) => { row.questionDraft.extra = "untrusted"; }],
    ["missing question draft value", (row: any) => { delete row.questionDraft.value; }],
    ["non-string question draft value", (row: any) => { row.questionDraft.value = 1; }],
    ["oversized question draft value", (row: any) => { row.questionDraft.value = "x".repeat(64_001); }],
    ["missing question draft question", (row: any) => { delete row.questionDraft.question; }],
    ["null question draft question", (row: any) => { row.questionDraft.question = null; }],
    ["non-object answer question", (row: any) => { row.outstanding.answerQuestion = "question"; }],
    ["null answer question", (row: any) => { row.outstanding.answerQuestion = null; }],
    ["answer question without preserveDraft", (row: any) => { delete row.outstanding.preserveDraft; }],
  ])("rejects %s without replacing existing recovery state", (_label, mutate) => {
    const storage = memoryStorage();
    const value = { ...pending(), questionDraft: { question: question(), value: "回答" },
      outstanding: { ...pending().outstanding!, answerQuestion: question() } };
    saveLauncherComposer("session", "floating", value, storage);
    const [key, raw] = [...storage.entries][0];
    const row = JSON.parse(raw);
    mutate(row.snapshot);
    expect(saveLauncherComposer("session", "floating", row.snapshot, storage)).toBe(false);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual(value);
    const invalid = JSON.stringify(row);
    storage.setItem(key, invalid);
    expect(loadLauncherComposer("session", "floating", storage)).toBeNull();
    expect(storage.getItem(key)).toBe(invalid);
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
    const value = { ...pending(), attachments, token: forbidden };
    expect(saveLauncherComposer("session", "floating", value, storage)).toBe(true);
    expect(loadLauncherComposer("session", "floating", storage)).toEqual({ ...pending(),
      attachments: [{ id: "chip-uploaded", artifactId: "user-image-1.png", filename: "shot.png",
        contentType: "image/png", sizeBytes: 1, kind: "image" }] });
    const savedSnapshot = JSON.parse([...storage.entries.values()][0]).snapshot;
    expect(Object.keys(savedSnapshot)).toEqual(["draft", "outstanding", "acceptedTurnId", "queuedAcceptance", "attachments"]);
    expect(JSON.stringify(savedSnapshot.attachments)).not.toContain("blob:");
    expect(JSON.stringify(savedSnapshot)).not.toContain("continuation");
  });

  it("loads envelopes written before attachment and question persistence with an empty tray", () => {
    const storage = memoryStorage();
    saveLauncherComposer("session", "floating", pending(), storage);
    const [key, raw] = [...storage.entries][0];
    const legacy = JSON.parse(raw);
    delete legacy.snapshot.attachments;
    delete legacy.snapshot.questionDraft;
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
    ["submission references outside the recovery whitelist", (row: any) => { row.snapshot.outstanding.references = [{ kind: "message", sourceMessageId: "m1", token: "secret" }]; }],
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

  it.each(["{", "null", "[]", "x".repeat(1_800_001)])("returns null for corrupt or oversized JSON", raw => {
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

  it("accepts four fully JSON-escaped maximum text fields and bounded question metadata", () => {
    const storage = memoryStorage();
    const maxText = "\u0000".repeat(64_000);
    const maxQuestion = { id: "q".repeat(255), questionText: "\u0000".repeat(4_000),
      askedAt: "t".repeat(64), turnId: "t".repeat(255) };
    const value = { ...empty(), draft: maxText, questionDraft: { question: maxQuestion, value: maxText },
      outstanding: { message: maxText, requestId: "r".repeat(128), draftSnapshot: maxText,
        preserveDraft: true as const, answerQuestion: maxQuestion } };
    expect(saveLauncherComposer("session", "embedded", value, storage)).toBe(true);
    const raw = [...storage.entries.values()][0];
    expect(raw.length).toBeGreaterThan(1_200_000);
    expect(raw.length).toBeLessThan(1_800_000);
    expect(loadLauncherComposer("session", "embedded", storage)).toEqual(value);
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
