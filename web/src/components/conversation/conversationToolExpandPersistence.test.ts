/** @vitest-environment happy-dom */
import { beforeEach, describe, expect, it } from "vitest";

import {
  capToolExpandEntries,
  openToolKeysForEntries,
  readOpenToolKeys,
  removeToolExpandEntry,
  resetToolExpandPersistenceForTests,
  setToolRowOpen,
  TOOL_EXPAND_MAX_ENTRIES,
  TOOL_EXPAND_STORAGE_KEY,
  upsertToolExpandEntry,
  type StoredToolExpandEntry,
} from "./conversationToolExpandPersistence";

function entry(sessionId: string, key: string): StoredToolExpandEntry {
  return { sessionId, key };
}

beforeEach(() => {
  localStorage.clear();
  resetToolExpandPersistenceForTests();
});

describe("conversationToolExpandPersistence pure helpers", () => {
  it("caps entries to the LRU window, deduping to the newest occurrence", () => {
    const entries = [
      entry("s1", "old-1"),
      entry("s1", "old-2"),
      entry("s1", "old-1"),
      ...Array.from({ length: TOOL_EXPAND_MAX_ENTRIES }, (_, index) => entry("s2", `fill-${index}`)),
      entry("s3", ""),
      entry("", "no-session"),
    ];
    const capped = capToolExpandEntries(entries);
    expect(capped).toHaveLength(TOOL_EXPAND_MAX_ENTRIES);
    // Dedupe leaves 514 distinct entries (old-2, old-1, 512 fills); the cap
    // keeps the newest 512, so the oldest pair drops with the overflow.
    expect(capped[0]).toEqual(entry("s2", "fill-0"));
    expect(capped.at(-1)).toEqual(entry("s2", `fill-${TOOL_EXPAND_MAX_ENTRIES - 1}`));
    expect(capped.some((item) => item.sessionId === "s1")).toBe(false);
    // Invalid rows (empty session or key) never survive the cap.
    expect(capped.some((item) => !item.sessionId || !item.key)).toBe(false);
  });

  it("upsert touches the entry to the newest position and collapse removes exactly one pair", () => {
    let entries: StoredToolExpandEntry[] = [entry("s1", "a"), entry("s1", "b"), entry("s2", "a")];
    entries = upsertToolExpandEntry(entries, "s1", "a");
    expect(entries.at(-1)).toEqual(entry("s1", "a"));
    expect(entries).toHaveLength(3);

    entries = removeToolExpandEntry(entries, "s1", "a");
    expect(entries).toEqual([entry("s1", "b"), entry("s2", "a")]);
    // Removal of an absent pair is a no-op; empty scope is a no-op too.
    expect(removeToolExpandEntry(entries, "s1", "missing")).toEqual(entries);
    expect(removeToolExpandEntry(entries, "", "b")).toEqual(entries);
  });

  it("openToolKeysForEntries isolates sessions and returns empty without a scope", () => {
    const entries = [entry("s1", "a"), entry("s1", "b"), entry("s2", "a")];
    expect([...openToolKeysForEntries(entries, "s1")].sort()).toEqual(["a", "b"]);
    expect([...openToolKeysForEntries(entries, "s2")]).toEqual(["a"]);
    expect(openToolKeysForEntries(entries, "").size).toBe(0);
  });
});

describe("conversationToolExpandPersistence storage", () => {
  it("stores open rows per session and reads them back after a reload", () => {
    setToolRowOpen("session-1", "tool-a", true);
    setToolRowOpen("session-1", "tool-b", true);
    setToolRowOpen("session-2", "tool-c", true);

    // Simulate a page reload: drop the module cache, re-read from localStorage.
    resetToolExpandPersistenceForTests();
    expect([...readOpenToolKeys("session-1")].sort()).toEqual(["tool-a", "tool-b"]);
    expect(readOpenToolKeys("session-2").has("tool-c")).toBe(true);
    expect(readOpenToolKeys("session-3").size).toBe(0);
    expect(JSON.parse(localStorage.getItem(TOOL_EXPAND_STORAGE_KEY)!)).toEqual([
      entry("session-1", "tool-a"),
      entry("session-1", "tool-b"),
      entry("session-2", "tool-c"),
    ]);
  });

  it("frees the stored entry on collapse", () => {
    setToolRowOpen("session-1", "tool-a", true);
    expect(readOpenToolKeys("session-1").has("tool-a")).toBe(true);
    setToolRowOpen("session-1", "tool-a", false);
    expect(readOpenToolKeys("session-1").size).toBe(0);
    expect(localStorage.getItem(TOOL_EXPAND_STORAGE_KEY)).toBe("[]");
  });

  it("skips persistence without a session scope", () => {
    setToolRowOpen("", "tool-a", true);
    setToolRowOpen("session-1", "", true);
    expect(localStorage.getItem(TOOL_EXPAND_STORAGE_KEY)).toBeNull();
    expect(readOpenToolKeys("").size).toBe(0);
  });

  it("silently resets corrupted JSON and heals on the next write", () => {
    localStorage.setItem(TOOL_EXPAND_STORAGE_KEY, "{not valid json");
    resetToolExpandPersistenceForTests();
    expect(readOpenToolKeys("session-1").size).toBe(0);
    setToolRowOpen("session-1", "tool-a", true);
    expect(JSON.parse(localStorage.getItem(TOOL_EXPAND_STORAGE_KEY)!)).toEqual([
      entry("session-1", "tool-a"),
    ]);
  });

  it("silently resets non-array storage shapes and drops malformed rows", () => {
    localStorage.setItem(TOOL_EXPAND_STORAGE_KEY, JSON.stringify({ sessions: {} }));
    resetToolExpandPersistenceForTests();
    expect(readOpenToolKeys("session-1").size).toBe(0);

    localStorage.setItem(TOOL_EXPAND_STORAGE_KEY, JSON.stringify([
      { sessionId: "session-1", key: "tool-a" },
      "garbage",
      null,
      { key: "missing-session" },
      { sessionId: 42, key: "tool-b" },
    ]));
    resetToolExpandPersistenceForTests();
    expect([...readOpenToolKeys("session-1")]).toEqual(["tool-a"]);
  });

  it("caps persisted entries at the LRU limit", () => {
    for (let index = 0; index < TOOL_EXPAND_MAX_ENTRIES + 10; index += 1) {
      setToolRowOpen("session-1", `tool-${index}`, true);
    }
    const stored: StoredToolExpandEntry[] = JSON.parse(localStorage.getItem(TOOL_EXPAND_STORAGE_KEY)!);
    expect(stored).toHaveLength(TOOL_EXPAND_MAX_ENTRIES);
    expect(stored[0]).toEqual(entry("session-1", "tool-10"));
    expect(stored.at(-1)).toEqual(entry("session-1", `tool-${TOOL_EXPAND_MAX_ENTRIES + 9}`));
  });
});
