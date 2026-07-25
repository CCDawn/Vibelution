import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  PANE_HEIGHT_STORAGE_KEY,
  clampPaneHeight,
  migrateLegacyNumericHeight,
  persistPaneHeight,
  readPaneHeights,
  resolveStoredPaneHeight,
  writePaneHeights,
} from "./paneHeightPersistence";

describe("paneHeightPersistence", () => {
  beforeEach(() => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    });
    vi.stubGlobal("window", { localStorage: globalThis.localStorage });
  });

  it("clamps heights to min/max", () => {
    expect(clampPaneHeight(100, 200, 400)).toBe(200);
    expect(clampPaneHeight(500, 200, 400)).toBe(400);
    expect(clampPaneHeight(300.4, 200, 400)).toBe(300);
  });

  it("persists heights by layoutId without clobbering siblings", () => {
    writePaneHeights("evolution", { "live-io": 340 });
    persistPaneHeight("evolution", "detail", 280);
    expect(readPaneHeights("evolution")).toEqual({
      "live-io": 340,
      detail: 280,
    });
    expect(localStorage.getItem(PANE_HEIGHT_STORAGE_KEY)).toContain("live-io");
  });

  it("migrates legacy single-key heights once", () => {
    localStorage.setItem("vibelution.evolution.live-io-height", "412");
    const height = resolveStoredPaneHeight(
      "evolution",
      "live-io",
      340,
      260,
      780,
      "vibelution.evolution.live-io-height",
    );
    expect(height).toBe(412);
    expect(readPaneHeights("evolution")).toEqual({ "live-io": 412 });

    localStorage.setItem("vibelution.evolution.live-io-height", "999");
    expect(
      resolveStoredPaneHeight(
        "evolution",
        "live-io",
        340,
        260,
        780,
        "vibelution.evolution.live-io-height",
      ),
    ).toBe(412);
  });

  it("skips migrate when shared height already exists", () => {
    writePaneHeights("evolution", { "live-io": 300 });
    localStorage.setItem("vibelution.evolution.live-io-height", "500");
    migrateLegacyNumericHeight("evolution", "live-io", "vibelution.evolution.live-io-height");
    expect(readPaneHeights("evolution")["live-io"]).toBe(300);
  });
});
