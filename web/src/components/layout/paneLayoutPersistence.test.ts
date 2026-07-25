import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  PANE_LAYOUT_STORAGE_KEY,
  clampPaneWidth,
  readAllPaneLayouts,
  readPaneLayout,
  resolvePaneWidths,
  writeAllPaneLayouts,
  writePaneLayout,
} from "./paneLayoutPersistence";

describe("paneLayoutPersistence", () => {
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

  it("clamps widths to min/max", () => {
    expect(clampPaneWidth(100, 200, 400)).toBe(200);
    expect(clampPaneWidth(500, 200, 400)).toBe(400);
    expect(clampPaneWidth(300.6, 200, 400)).toBe(301);
  });

  it("persists layout widths by layoutId for permanent memory", () => {
    writePaneLayout("skills", { sidebar: 280 });
    writePaneLayout("agents", { left: 340, right: 360 });

    expect(readPaneLayout("skills")).toEqual({ sidebar: 280 });
    expect(readPaneLayout("agents")).toEqual({ left: 340, right: 360 });
    expect(readAllPaneLayouts()).toEqual({
      skills: { sidebar: 280 },
      agents: { left: 340, right: 360 },
    });
    expect(localStorage.getItem(PANE_LAYOUT_STORAGE_KEY)).toContain("skills");
  });

  it("resolves missing panes to defaults within clamp", () => {
    writePaneLayout("skills", { sidebar: 9999 });
    const resolved = resolvePaneWidths("skills", [
      { id: "sidebar", defaultWidth: 320, minWidth: 220, maxWidth: 480 },
      { id: "aside", defaultWidth: 300, minWidth: 240, maxWidth: 400 },
    ]);
    expect(resolved.sidebar).toBe(480);
    expect(resolved.aside).toBe(300);
  });

  it("overwrites a layout without clearing siblings", () => {
    writeAllPaneLayouts({ a: { x: 1 }, b: { y: 2 } });
    writePaneLayout("a", { x: 3, z: 4 });
    expect(readAllPaneLayouts()).toEqual({
      a: { x: 3, z: 4 },
      b: { y: 2 },
    });
  });
});
