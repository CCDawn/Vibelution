import { describe, expect, it } from "vitest";

import {
  DEFAULT_SESSION_LIST_PREFERENCES,
  loadSessionListPreferences,
  normalizeSessionListPreferences,
  normalizeSessionListSortBy,
  saveSessionListPreferences,
  sessionListSortQueryValue,
} from "./sessionListPreferences";

function memoryStorage(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
  };
}

describe("sessionListPreferences", () => {
  it("defaults to updatedAt order with timeline grouping off", () => {
    expect(DEFAULT_SESSION_LIST_PREFERENCES).toEqual({
      sortBy: "updatedAt",
      timelineGrouping: false,
    });
    expect(loadSessionListPreferences(memoryStorage())).toEqual(
      DEFAULT_SESSION_LIST_PREFERENCES,
    );
    expect(loadSessionListPreferences(null)).toEqual(DEFAULT_SESSION_LIST_PREFERENCES);
  });

  it("round-trips preferences through storage", () => {
    const storage = memoryStorage();
    saveSessionListPreferences({ sortBy: "createdAt", timelineGrouping: true }, storage);
    expect(loadSessionListPreferences(storage)).toEqual({
      sortBy: "createdAt",
      timelineGrouping: true,
    });
  });

  it("normalizes corrupt payloads to defaults", () => {
    expect(normalizeSessionListPreferences(null)).toEqual(DEFAULT_SESSION_LIST_PREFERENCES);
    expect(normalizeSessionListPreferences("junk")).toEqual(DEFAULT_SESSION_LIST_PREFERENCES);
    expect(normalizeSessionListPreferences({ sortBy: "weird", timelineGrouping: "yes" })).toEqual({
      sortBy: "updatedAt",
      timelineGrouping: false,
    });
    expect(normalizeSessionListSortBy("createdAt")).toBe("createdAt");
    expect(normalizeSessionListSortBy(undefined)).toBe("updatedAt");
  });

  it("maps the sort preference onto backend sort values", () => {
    expect(sessionListSortQueryValue("updatedAt")).toBe("updatedAt_desc");
    expect(sessionListSortQueryValue("createdAt")).toBe("createdAt_desc");
  });

  it("survives malformed stored JSON", () => {
    const storage = { getItem: () => "{not json", setItem: () => undefined };
    expect(loadSessionListPreferences(storage)).toEqual(DEFAULT_SESSION_LIST_PREFERENCES);
  });
});
