// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  CHAT_DRAFTS_MAX_SESSIONS,
  CHAT_DRAFTS_STORAGE_KEY,
  CHAT_DRAFT_MAX_CHARS,
  capStoredSessionDrafts,
  clampStoredSessionDraft,
  flushPendingSessionDraftWrites,
  readStoredSessionDrafts,
  removeStoredSessionDraft,
  resetChatDraftPersistenceForTests,
  scheduleSessionDraftSave,
  upsertStoredSessionDraft,
  type StoredSessionDraftEntry,
} from "./chatDraftPersistence";

function storedRaw(): string | null {
  return localStorage.getItem(CHAT_DRAFTS_STORAGE_KEY);
}

function storedEntry(sessionId: string): string | undefined {
  const raw = storedRaw();
  if (!raw) {
    return undefined;
  }
  const entries = JSON.parse(raw) as Array<{ sessionId: string; draft: string }>;
  return entries.find((entry) => entry.sessionId === sessionId)?.draft;
}

describe("chatDraftPersistence", () => {
  beforeEach(() => {
    localStorage.clear();
    resetChatDraftPersistenceForTests();
  });
  afterEach(() => {
    resetChatDraftPersistenceForTests();
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

  it("caps stored drafts to an LRU window of sessions", () => {
    expect(CHAT_DRAFTS_MAX_SESSIONS).toBe(20);
    for (let index = 1; index <= 25; index += 1) {
      scheduleSessionDraftSave(`session-${index}`, `draft-${index}`);
      flushPendingSessionDraftWrites();
    }
    expect(readStoredSessionDrafts()["session-1"]).toBeUndefined();
    expect(readStoredSessionDrafts()["session-5"]).toBeUndefined();
    expect(readStoredSessionDrafts()["session-6"]).toBe("draft-6");
    expect(readStoredSessionDrafts()["session-25"]).toBe("draft-25");
    expect(Object.keys(readStoredSessionDrafts())).toHaveLength(20);
  });

  it("touches a session on re-save so recently edited drafts survive the cap", () => {
    let entries: StoredSessionDraftEntry[] = [];
    for (let index = 1; index <= 20; index += 1) {
      entries = upsertStoredSessionDraft(entries, `session-${index}`, `draft-${index}`);
    }
    expect(entries).toHaveLength(20);
    // Re-saving the oldest session moves it to the newest slot.
    entries = upsertStoredSessionDraft(entries, "session-1", "draft-1-touched");
    entries = upsertStoredSessionDraft(entries, "session-21", "draft-21");
    expect(entries).toHaveLength(20);
    expect(entries.find((entry) => entry.sessionId === "session-1")?.draft).toBe("draft-1-touched");
    expect(entries.find((entry) => entry.sessionId === "session-2")).toBeUndefined();
    expect(capStoredSessionDrafts(entries)).toHaveLength(20);
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
});
