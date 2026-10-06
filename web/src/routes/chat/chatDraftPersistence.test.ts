// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  CHAT_DRAFTS_MAX_SESSIONS,
  CHAT_DRAFTS_STORAGE_KEY,
  CHAT_DRAFT_MAX_CHARS,
  moveStoredSessionDraft,
  capStoredSessionDrafts,
  beginSessionDraftRecoveryGuard,
  clampStoredSessionDraft,
  flushPendingSessionDraftWrites,
  readStoredSessionDrafts,
  readStoredSessionDraftState,
  removeStoredSessionDraft,
  scheduleSessionDraftRecoverySave,
  resetChatDraftPersistenceForTests,
  sanitizeStoredDraftReferences,
  scheduleSessionDraftMetaSave,
  scheduleSessionDraftSave,
  upsertStoredSessionDraft,
  upsertStoredSessionDraftMeta,
  type StoredSessionDraftEntry,
} from "./chatDraftPersistence";

function storedRaw(): string | null {
  return localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY);
}

function storedEntries(): Array<Record<string, unknown>> {
  const raw = storedRaw();
  if (!raw) {
    return [];
  }
  return JSON.parse(raw) as Array<Record<string, unknown>>;
}

function storedEntry(sessionId: string): string | undefined {
  return storedEntries().find((entry) => entry.sessionId === sessionId)?.draft as string | undefined;
}

describe("chatDraftPersistence", () => {
  beforeEach(() => {
    localStorage.clear();
    resetChatDraftPersistenceForTests();
  });
  afterEach(() => {
    resetChatDraftPersistenceForTests();
  });

  it.each([false, true])("moves a create draft and metadata before reload (already flushed: %s)", (flushed) => {
    scheduleSessionDraftSave("temp", "original");
    scheduleSessionDraftMetaSave("temp", { turnModelSelection: { modelId: "chosen" }, referenceAttachments: [{ kind: "session", sessionId: "source" }] });
    scheduleSessionDraftSave("other", "independent");
    if (flushed) flushPendingSessionDraftWrites();
    scheduleSessionDraftSave("temp", "latest");
    moveStoredSessionDraft("temp", "real");
    expect(readStoredSessionDraftState()).toMatchObject({
      drafts: { real: "latest", other: "independent" },
      turnModelSelections: { real: { modelId: "chosen" } },
      referenceAttachments: { real: [{ kind: "session", sessionId: "source" }] },
    });
    expect(readStoredSessionDrafts().temp).toBeUndefined();
    window.dispatchEvent(new Event("pagehide"));
    expect(readStoredSessionDrafts()).toEqual({ real: "latest", other: "independent" });
  });

  it("does not overwrite a newer draft already stored under the real id", () => {
    scheduleSessionDraftSave("temp", "old");
    scheduleSessionDraftSave("real", "new");
    moveStoredSessionDraft("temp", "real");
    expect(readStoredSessionDrafts()).toEqual({ real: "new" });
    moveStoredSessionDraft("temp", "real");
    expect(readStoredSessionDrafts()).toEqual({ real: "new" });
  });

  it("keeps a newer explicit clear under the real id", () => {
    scheduleSessionDraftSave("temp", "old");
    scheduleSessionDraftSave("real", "");
    moveStoredSessionDraft("temp", "real");
    window.dispatchEvent(new Event("pagehide"));
    expect(readStoredSessionDrafts()).toEqual({});
  });

  it("persists drafts under the vibelution.chat.drafts.v1 key on a debounce", () => {
    scheduleSessionDraftSave("session-1", "未发送的草稿");
    // Not written synchronously: keystroke-rate changes never hit storage.
    expect(storedRaw()).toBeNull();

    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toBe("未发送的草稿");
  });

  it("coalesces bursts into the latest draft value for the session", () => {
    scheduleSessionDraftSave("session-1", "第一版");
    scheduleSessionDraftSave("session-1", "第二版");
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toBe("第二版");
  });

  it("flushes pending text and metadata when the document leaves before the debounce", () => {
    scheduleSessionDraftSave("session-1", "最后输入的草稿");
    scheduleSessionDraftMetaSave("session-1", { turnModelSelection: { modelId: "model-1" } });
    expect(storedRaw()).toBeNull();

    window.dispatchEvent(new Event("pagehide"));

    expect(storedEntry("session-1")).toBe("最后输入的草稿");
    expect(readStoredSessionDraftState().turnModelSelections["session-1"]).toEqual({ modelId: "model-1" });
  });

  it("never resurrects a submitted draft when the page hides", () => {
    scheduleSessionDraftSave("session-1", "已经发送");
    scheduleSessionDraftSave("session-2", "另一个会话仍未发送");
    removeStoredSessionDraft("session-1");

    window.dispatchEvent(new Event("pagehide"));

    expect(readStoredSessionDrafts()).toEqual({ "session-2": "另一个会话仍未发送" });
  });

  it("hydrates the in-memory draft map and ignores corrupted storage", () => {
    scheduleSessionDraftSave("session-1", "草稿甲");
    scheduleSessionDraftSave("session-2", "草稿乙");
    flushPendingSessionDraftWrites();
    expect(readStoredSessionDrafts()).toEqual({ "session-1": "草稿甲", "session-2": "草稿乙" });

    localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, "{not-json");
    expect(readStoredSessionDrafts()).toEqual({});

    localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, JSON.stringify({ not: "an array" }));
    expect(readStoredSessionDrafts()).toEqual({});
  });

  it("caps stored drafts to an LRU window of 50 sessions", () => {
    expect(CHAT_DRAFTS_MAX_SESSIONS).toBe(50);
    for (let index = 1; index <= 55; index += 1) {
      scheduleSessionDraftSave(`session-${index}`, `draft-${index}`);
      flushPendingSessionDraftWrites();
    }
    expect(readStoredSessionDrafts()["session-1"]).toBeUndefined();
    expect(readStoredSessionDrafts()["session-5"]).toBeUndefined();
    expect(readStoredSessionDrafts()["session-6"]).toBe("draft-6");
    expect(readStoredSessionDrafts()["session-55"]).toBe("draft-55");
    expect(Object.keys(readStoredSessionDrafts())).toHaveLength(50);
  });

  it("touches a session on re-save so recently edited drafts survive the cap", () => {
    let entries: StoredSessionDraftEntry[] = [];
    for (let index = 1; index <= 50; index += 1) {
      entries = upsertStoredSessionDraft(entries, `session-${index}`, `draft-${index}`);
    }
    expect(entries).toHaveLength(50);
    // Re-saving the oldest session moves it to the newest slot.
    entries = upsertStoredSessionDraft(entries, "session-1", "draft-1-touched");
    entries = upsertStoredSessionDraft(entries, "session-51", "draft-51");
    expect(entries).toHaveLength(50);
    expect(entries.find((entry) => entry.sessionId === "session-1")?.draft).toBe("draft-1-touched");
    expect(entries.find((entry) => entry.sessionId === "session-2")).toBeUndefined();
    expect(capStoredSessionDrafts(entries)).toHaveLength(50);
  });

  it("truncates oversized drafts to the 64KB cap", () => {
    expect(CHAT_DRAFT_MAX_CHARS).toBe(64 * 1024);
    const oversized = "字".repeat(CHAT_DRAFT_MAX_CHARS + 100);
    scheduleSessionDraftSave("session-1", oversized);
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toHaveLength(CHAT_DRAFT_MAX_CHARS);
    expect(clampStoredSessionDraft("短草稿")).toBe("短草稿");
  });

  it("drops empty drafts instead of storing them", () => {
    scheduleSessionDraftSave("session-1", "草稿");
    flushPendingSessionDraftWrites();
    scheduleSessionDraftSave("session-1", "");
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toBeUndefined();
    expect(readStoredSessionDrafts()).toEqual({});
  });

  it("removes a submitted session draft immediately and cancels pending writes", () => {
    scheduleSessionDraftSave("session-1", "即将发送");
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toBe("即将发送");
    removeStoredSessionDraft("session-1");
    expect(storedEntry("session-1")).toBeUndefined();

    // A pending save followed by removal must not resurrect the draft.
    scheduleSessionDraftSave("session-2", "待写入后删除");
    removeStoredSessionDraft("session-2");
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-2")).toBeUndefined();
    expect(readStoredSessionDrafts()).toEqual({});
  });

  it("rejects failed-submit recovery after a newer composer edit", () => {
    const guard = beginSessionDraftRecoveryGuard("session-1");
    expect(guard).not.toBeNull();

    scheduleSessionDraftSave("session-1", "用户后来输入的草稿");

    expect(scheduleSessionDraftRecoverySave(guard, "已经提交的旧内容")).toBe(false);
    flushPendingSessionDraftWrites();
    expect(storedEntry("session-1")).toBe("用户后来输入的草稿");
  });

  it("persists rich meta (turn model selection + reference chips) next to the draft text", () => {
    scheduleSessionDraftSave("session-1", "带引用的草稿");
    flushPendingSessionDraftWrites();
    scheduleSessionDraftMetaSave("session-1", {
      turnModelSelection: { modelId: "glm-5.3", reasoningEffort: "high" },
      referenceAttachments: [
        { kind: "session", sessionId: "other-1", title: "参考会话" },
        { kind: "knowledge_item", knowledgeItemId: "kb-item-1", title: "架构笔记" },
      ],
    });
    flushPendingSessionDraftWrites();

    const entry = storedEntries().find((row) => row.sessionId === "session-1");
    expect(entry?.draft).toBe("带引用的草稿");
    expect(entry?.turnModelSelection).toEqual({ modelId: "glm-5.3", reasoningEffort: "high" });
    expect(entry?.referenceAttachments).toEqual([
      { kind: "session", sessionId: "other-1", title: "参考会话" },
      { kind: "knowledge_item", knowledgeItemId: "kb-item-1", title: "架构笔记" },
    ]);

    const state = readStoredSessionDraftState();
    expect(state.drafts["session-1"]).toBe("带引用的草稿");
    expect(state.turnModelSelections["session-1"]).toEqual({ modelId: "glm-5.3", reasoningEffort: "high" });
    expect(state.referenceAttachments["session-1"]).toHaveLength(2);
  });

  it("keeps the draft text when only meta changes, and keeps meta when only text changes", () => {
    scheduleSessionDraftSave("session-1", "正文");
    scheduleSessionDraftMetaSave("session-1", {
      turnModelSelection: { modelId: "glm-5.3" },
      referenceAttachments: [{ kind: "session", sessionId: "other-1", title: "参考" }],
    });
    flushPendingSessionDraftWrites();

    scheduleSessionDraftSave("session-1", "正文第二版");
    flushPendingSessionDraftWrites();
    let entry = storedEntries().find((row) => row.sessionId === "session-1");
    expect(entry?.draft).toBe("正文第二版");
    expect(entry?.turnModelSelection).toEqual({ modelId: "glm-5.3" });

    scheduleSessionDraftMetaSave("session-1", {
      turnModelSelection: { modelId: "glm-4.7" },
    });
    flushPendingSessionDraftWrites();
    entry = storedEntries().find((row) => row.sessionId === "session-1");
    expect(entry?.draft).toBe("正文第二版");
    expect(entry?.turnModelSelection).toEqual({ modelId: "glm-4.7" });
    // Unspecified meta fields stay untouched (reference chips survive).
    expect(entry?.referenceAttachments).toEqual([{ kind: "session", sessionId: "other-1", title: "参考" }]);
  });

  it("round-trips reference-only sessions (chips survive a reload with no text)", () => {
    scheduleSessionDraftMetaSave("session-1", {
      referenceAttachments: [{ kind: "message", sourceSessionId: "src-1", sourceMessageId: "m-1", quote: "引用原文" }],
    });
    flushPendingSessionDraftWrites();
    // The entry stays as meta-only: draft text is empty, chips persist.
    expect(storedEntries().find((row) => row.sessionId === "session-1")?.draft ?? "").toBe("");

    const state = readStoredSessionDraftState();
    expect(state.drafts["session-1"]).toBeUndefined();
    expect(state.referenceAttachments["session-1"]).toEqual([
      { kind: "message", sourceSessionId: "src-1", sourceMessageId: "m-1", quote: "引用原文" },
    ]);

    // Clearing the last chip drops the meta-only entry.
    scheduleSessionDraftMetaSave("session-1", { referenceAttachments: [] });
    flushPendingSessionDraftWrites();
    expect(storedEntries().find((row) => row.sessionId === "session-1")).toBeUndefined();
  });

  it("migrates old plain-text entries on read and sanitizes untrusted rich fields", () => {
    // Legacy writer shape: {sessionId, draft} only.
    localStorage.setItem(CHAT_DRAFTS_STORAGE_KEY, JSON.stringify([
      { sessionId: "legacy-1", draft: "旧纯文本草稿" },
      {
        sessionId: "rich-1",
        draft: "富草稿",
        turnModelSelection: { modelId: "glm-5.3", reasoningEffort: "high", smuggled: "x" },
        referenceAttachments: [
          { kind: "session", sessionId: "other-1", title: "参考", evil: () => undefined },
          { kind: "file", title: "无身份的引用" },
          "not-an-object",
        ],
      },
      { sessionId: "", draft: "无会话" },
    ]));

    const state = readStoredSessionDraftState();
    // Plain-text entry reads back unchanged; no write-back migration needed.
    expect(state.drafts["legacy-1"]).toBe("旧纯文本草稿");
    expect(state.turnModelSelections["legacy-1"]).toBeUndefined();
    // Rich fields come back allow-listed; identity-less references are dropped.
    expect(state.turnModelSelections["rich-1"]).toEqual({ modelId: "glm-5.3", reasoningEffort: "high" });
    expect(state.referenceAttachments["rich-1"]).toEqual([
      { kind: "session", sessionId: "other-1", title: "参考" },
    ]);
  });

  it("bounds reference chips per draft and rejects non-string metadata", () => {
    const many = Array.from({ length: 12 }, (_, index) => ({
      kind: "session",
      sessionId: `other-${index}`,
      title: `参考 ${index}`,
    }));
    expect(sanitizeStoredDraftReferences(many)).toHaveLength(8);
    // Non-string identity, null rows, and title-only decoration are all dropped:
    // a chip that cannot be re-identified must not resurrect as a dead chip.
    expect(sanitizeStoredDraftReferences([
      { kind: "session", sessionId: 42 },
      null,
      { title: "只有标题" },
    ])).toEqual([]);
  });

  it("upsertStoredSessionDraftMeta merges into an existing entry and drops empty results", () => {
    let entries: StoredSessionDraftEntry[] = upsertStoredSessionDraft([], "session-1", "正文");
    entries = upsertStoredSessionDraftMeta(entries, "session-1", {
      turnModelSelection: { modelId: "glm-5.3" },
    });
    expect(entries).toHaveLength(1);
    expect(entries[0].draft).toBe("正文");
    expect(entries[0].turnModelSelection).toEqual({ modelId: "glm-5.3" });

    entries = upsertStoredSessionDraftMeta(entries, "session-1", {
      turnModelSelection: null,
      referenceAttachments: [],
    });
    // Text-only entry stays (clearing meta keeps the draft).
    expect(entries).toHaveLength(1);
    expect(entries[0].draft).toBe("正文");
    expect(entries[0].turnModelSelection).toBeNull();
    expect(entries[0].referenceAttachments).toEqual([]);

    // Removing the draft text leaves a meta-only entry alive while chips exist.
    entries = upsertStoredSessionDraftMeta(entries, "session-1", {
      referenceAttachments: [{ kind: "session", sessionId: "other-1" }],
    });
    entries = upsertStoredSessionDraft(entries, "session-1", "");
    expect(entries).toHaveLength(1);
    expect(entries[0].draft).toBe("");
    expect(entries[0].referenceAttachments).toEqual([{ kind: "session", sessionId: "other-1" }]);
  });
});
