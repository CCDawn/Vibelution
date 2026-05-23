import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clampPaneSize,
  clampPaneWidth,
  keyboardPaneHeight,
  keyboardPaneWidth,
  storedPaneSize,
  storedPaneWidth,
} from "./resizablePane";

function stubWindowStorage(values: Record<string, string>) {
  vi.stubGlobal("window", {
    localStorage: {
      getItem: (key: string) => values[key] ?? null,
    },
  });
}

describe("resizablePane", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("clamps widths to the configured bounds", () => {
    expect(clampPaneWidth(120, { min: 240, max: 520 })).toBe(240);
    expect(clampPaneWidth(800, { min: 240, max: 520 })).toBe(520);
    expect(clampPaneWidth(411.6, { min: 240, max: 520 })).toBe(412);
  });

  it("uses stored widths when they are valid", () => {
    stubWindowStorage({ "vibelution.test-pane": "480" });

    expect(storedPaneWidth("vibelution.test-pane", 320, { min: 240, max: 520 })).toBe(480);
  });

  it("falls back when stored widths are invalid", () => {
    stubWindowStorage({ "vibelution.test-pane": "not-a-number" });

    expect(storedPaneWidth("vibelution.test-pane", 360, { min: 240, max: 520 })).toBe(360);
  });

  it("maps keyboard actions to width changes", () => {
    expect(keyboardPaneWidth(360, "ArrowRight", { min: 240, max: 520 })).toBe(384);
    expect(keyboardPaneWidth(360, "ArrowLeft", { min: 240, max: 520 })).toBe(336);
    expect(keyboardPaneWidth(360, "Home", { min: 240, max: 520 })).toBe(240);
    expect(keyboardPaneWidth(360, "End", { min: 240, max: 520 })).toBe(520);
    expect(keyboardPaneWidth(360, "Enter", { min: 240, max: 520 })).toBeNull();
  });

  it("maps keyboard actions to height changes", () => {
    expect(clampPaneSize(180, { min: 240, max: 700 })).toBe(240);
    expect(storedPaneSize("vibelution.test-pane", 360, { min: 240, max: 700 })).toBe(360);
    expect(keyboardPaneHeight(420, "ArrowDown", { min: 240, max: 700 })).toBe(444);
    expect(keyboardPaneHeight(420, "ArrowUp", { min: 240, max: 700 })).toBe(396);
    expect(keyboardPaneHeight(420, "Home", { min: 240, max: 700 })).toBe(240);
    expect(keyboardPaneHeight(420, "End", { min: 240, max: 700 })).toBe(700);
    expect(keyboardPaneHeight(420, "ArrowRight", { min: 240, max: 700 })).toBeNull();
  });

  it("supports inverted keyboard direction for right-side panes", () => {
    expect(keyboardPaneWidth(360, "ArrowRight", { min: 240, max: 520 }, true)).toBe(336);
    expect(keyboardPaneWidth(360, "ArrowLeft", { min: 240, max: 520 }, true)).toBe(384);
  });

  it("does not require window during server-side evaluation", () => {
    vi.stubGlobal("window", undefined);

    expect(storedPaneWidth("vibelution.missing-window", 360, { min: 240, max: 520 })).toBe(360);
  });
});
