/** @vitest-environment happy-dom */
import { afterEach, describe, expect, it } from "vitest";

import {
  MAX_PROMPT_HISTORY,
  PROMPT_HISTORY_STORAGE_KEY,
  appendPromptHistoryEntry,
  appendStoredPromptHistoryEntry,
  navigatePromptHistory,
  readPromptHistory,
} from "./conversationPromptHistory";

afterEach(() => {
  window.localStorage.removeItem(PROMPT_HISTORY_STORAGE_KEY);
});

describe("appendPromptHistoryEntry", () => {
  it("trims the entry and skips empty/whitespace-only prompts", () => {
    expect(appendPromptHistoryEntry([], "  ")).toEqual([]);
    expect(appendPromptHistoryEntry([], "  修复登录页  ")).toEqual(["修复登录页"]);
  });

  it("does not append when the entry equals the latest one", () => {
    const entries = ["a", "b"];
    expect(appendPromptHistoryEntry(entries, "b ")).toEqual(["a", "b"]);
  });

  it("keeps non-adjacent duplicates (A, B, A)", () => {
    const entries = appendPromptHistoryEntry(["a", "b"], "a");
    expect(entries).toEqual(["a", "b", "a"]);
  });

  it("caps the history at the limit by dropping the oldest entries", () => {
    const full = Array.from({ length: MAX_PROMPT_HISTORY }, (_, i) => `p${i}`);
    const next = appendPromptHistoryEntry(full, "p-new");
    expect(next).toHaveLength(MAX_PROMPT_HISTORY);
    expect(next[0]).toBe("p1");
    expect(next.at(-1)).toBe("p-new");
  });

  it("does not mutate the input array", () => {
    const entries = ["a"];
    appendPromptHistoryEntry(entries, "b");
    expect(entries).toEqual(["a"]);
  });

  it("treats a custom limit below one as a single-entry history", () => {
    expect(appendPromptHistoryEntry(["a", "b"], "c", 0)).toEqual(["c"]);
  });
});

describe("navigatePromptHistory", () => {
  const entries = ["p0", "p1", "p2"];

  it("refuses to handle an empty history", () => {
    expect(navigatePromptHistory([], null, "up")).toEqual({
      nextIndex: null,
      nextValue: "",
      shouldHandle: false,
    });
  });

  it("starts at the newest entry on the first ArrowUp", () => {
    expect(navigatePromptHistory(entries, null, "up")).toEqual({
      nextIndex: 2,
      nextValue: "p2",
      shouldHandle: true,
    });
  });

  it("walks older entries on repeated ArrowUp and clamps at the oldest", () => {
    expect(navigatePromptHistory(entries, 2, "up")?.nextValue).toBe("p1");
    expect(navigatePromptHistory(entries, 1, "up")?.nextValue).toBe("p0");
    const clamped = navigatePromptHistory(entries, 0, "up");
    expect(clamped).toEqual({ nextIndex: 0, nextValue: "p0", shouldHandle: true });
  });

  it("walks newer entries on ArrowDown", () => {
    expect(navigatePromptHistory(entries, 0, "down")?.nextValue).toBe("p1");
    expect(navigatePromptHistory(entries, 1, "down")?.nextValue).toBe("p2");
  });

  it("hands back to the stashed draft past the newest entry on ArrowDown", () => {
    expect(navigatePromptHistory(entries, 2, "down")).toEqual({
      nextIndex: null,
      nextValue: "",
      shouldHandle: true,
    });
  });

  it("treats out-of-range indexes safely", () => {
    // Stale index after the list shrank: ArrowUp clamps back into range.
    expect(navigatePromptHistory(entries, 99, "up")?.nextIndex).toBe(2);
    // ArrowDown from a stale index still terminates the browse mode.
    expect(navigatePromptHistory(entries, 99, "down")?.nextIndex).toBeNull();
  });

  it("handles a single-entry history in both directions", () => {
    expect(navigatePromptHistory(["only"], null, "up")?.nextValue).toBe("only");
    expect(navigatePromptHistory(["only"], 0, "down")?.nextIndex).toBeNull();
  });
});

describe("stored history helpers", () => {
  it("round-trips through localStorage under the v1 key", () => {
    appendStoredPromptHistoryEntry("first");
    appendStoredPromptHistoryEntry("second");
    expect(window.localStorage.getItem(PROMPT_HISTORY_STORAGE_KEY)).toEqual(
      JSON.stringify(["first", "second"]),
    );
    expect(readPromptHistory()).toEqual(["first", "second"]);
  });

  it("returns an empty list for missing, corrupt, or non-array payloads", () => {
    expect(readPromptHistory()).toEqual([]);
    window.localStorage.setItem(PROMPT_HISTORY_STORAGE_KEY, "not-json");
    expect(readPromptHistory()).toEqual([]);
    window.localStorage.setItem(PROMPT_HISTORY_STORAGE_KEY, JSON.stringify({ nope: 1 }));
    expect(readPromptHistory()).toEqual([]);
    window.localStorage.setItem(PROMPT_HISTORY_STORAGE_KEY, JSON.stringify(["ok", 3, null, "also-ok"]));
    expect(readPromptHistory()).toEqual(["ok", "also-ok"]);
  });

  it("tolerates a null storage backend", () => {
    expect(appendStoredPromptHistoryEntry("x", null)).toEqual([]);
    expect(readPromptHistory(null)).toEqual([]);
  });
});
