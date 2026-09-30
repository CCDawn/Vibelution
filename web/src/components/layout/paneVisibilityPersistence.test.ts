import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PANE_VISIBILITY_STORAGE_KEY, persistPaneVisibility, readPaneVisibility } from "./paneVisibilityPersistence";

describe("pane visibility memory", () => {
  beforeEach(() => {
    const values = new Map<string, string>();
    vi.stubGlobal("window", { localStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    } });
  });
  afterEach(() => vi.unstubAllGlobals());
  it("preserves sibling panes and layouts including explicit false", () => {
    expect(readPaneVisibility("evolution", "run-navigation", true)).toBe(true);
    persistPaneVisibility("evolution", "run-navigation", false);
    persistPaneVisibility("other", "rail", true);
    persistPaneVisibility("evolution", "evidence", true);
    expect(readPaneVisibility("evolution", "run-navigation", true)).toBe(false);
    expect(readPaneVisibility("other", "rail", false)).toBe(true);
  });
  it("falls back safely for corrupt, invalid or inaccessible storage", () => {
    for (const raw of ["broken", "null", "[]", '{"evolution":{"run-navigation":"false"}}']) {
      window.localStorage.setItem(PANE_VISIBILITY_STORAGE_KEY, raw);
      expect(readPaneVisibility("evolution", "run-navigation", true)).toBe(true);
    }
    vi.stubGlobal("window", { get localStorage() { throw new Error("denied"); } });
    expect(readPaneVisibility("evolution", "run-navigation", true)).toBe(true);
    expect(() => persistPaneVisibility("evolution", "run-navigation", false)).not.toThrow();
  });
});
