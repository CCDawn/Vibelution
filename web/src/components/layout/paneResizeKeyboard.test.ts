import { describe, expect, it } from "vitest";

import {
  PANE_KEYBOARD_STEP,
  isPaneResizeKeyboardKey,
  resolvePaneWidthFromKeyboardKey,
} from "./paneResizeKeyboard";

describe("paneResizeKeyboard", () => {
  const bounds = { minWidth: 200, maxWidth: 400, currentWidth: 300 };

  it("steps with ArrowLeft/ArrowRight and respects direction", () => {
    expect(resolvePaneWidthFromKeyboardKey("ArrowRight", bounds)).toBe(300 + PANE_KEYBOARD_STEP);
    expect(resolvePaneWidthFromKeyboardKey("ArrowLeft", bounds)).toBe(300 - PANE_KEYBOARD_STEP);
    expect(
      resolvePaneWidthFromKeyboardKey("ArrowRight", { ...bounds, direction: -1 }),
    ).toBe(300 - PANE_KEYBOARD_STEP);
  });

  it("jumps to min/max with Home/End", () => {
    expect(resolvePaneWidthFromKeyboardKey("Home", bounds)).toBe(200);
    expect(resolvePaneWidthFromKeyboardKey("End", bounds)).toBe(400);
  });

  it("clamps stepped values to bounds", () => {
    expect(
      resolvePaneWidthFromKeyboardKey("ArrowRight", {
        ...bounds,
        currentWidth: 390,
        step: 24,
      }),
    ).toBe(400);
    expect(
      resolvePaneWidthFromKeyboardKey("ArrowLeft", {
        ...bounds,
        currentWidth: 210,
        step: 24,
      }),
    ).toBe(200);
  });

  it("ignores unrelated keys", () => {
    expect(resolvePaneWidthFromKeyboardKey("Enter", bounds)).toBeNull();
    expect(isPaneResizeKeyboardKey("ArrowLeft")).toBe(true);
    expect(isPaneResizeKeyboardKey("Home")).toBe(true);
    expect(isPaneResizeKeyboardKey("a")).toBe(false);
  });
});
